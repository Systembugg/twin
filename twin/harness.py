"""The harness loop.

Stateless by construction: every piece of state is either passed in or
persisted out, so the same function serves a fresh run and the resumption of a
run whose worker was killed mid-flight.

The correctness rules encoded here are the ones that fail silently if you get
them wrong:

* The **entire** ``response.content`` is appended to history. Keeping only the
  text drops ``tool_use`` and ``thinking`` blocks and the next request is
  rejected.
* Every ``tool_use`` gets exactly one ``tool_result`` with the matching
  ``tool_use_id``, and when the model calls tools in parallel **all** results go
  back in a single user message. Splitting them across messages is accepted by
  the API but teaches the model to stop parallelising.
* Tool inputs are read as parsed JSON, never string-matched.
* ``pause_turn`` is resumed by re-sending, not treated as completion.
* History is persisted after the model turn *and* after the tool batch, so
  there is no window in which a crash leaves an unsendable history.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from twin.compaction import compact
from twin.config import Caps
from twin.errors import BudgetExceeded
from twin.events import EventEmitter, EventType
from twin.hooks import Decision, HookRegistry, PermissionPolicy
from twin.limits import RunBudget
from twin.llm.client import ModelClient, Usage
from twin.persona import SystemPrompt
from twin.sandbox.base import Sandbox
from twin.store.base import ConversationStore, RunStatus
from twin.tools.base import ToolContext, ToolResult
from twin.tools.registry import ToolRegistry
from twin.tools.todo import SCRATCH_KEY as TODO_KEY

log = logging.getLogger(__name__)

#: stop_reasons that mean "the model is done talking for this turn".
_TERMINAL_STOPS = {"end_turn", "stop_sequence", "max_tokens", "refusal"}


@dataclass
class HarnessDeps:
    """Everything the loop needs, injected.

    Nothing here is looked up from a global, which is what lets a test run the
    real loop against fakes and what lets the sandbox backend be swapped
    without touching this module.
    """

    model: ModelClient
    registry: ToolRegistry
    store: ConversationStore
    sandbox: Sandbox
    system_prompt: SystemPrompt
    caps: Caps = field(default_factory=Caps)
    hooks: HookRegistry = field(default_factory=HookRegistry)
    permissions: PermissionPolicy = field(default_factory=PermissionPolicy)
    #: Cheap model used only for compaction summaries. A separate call with its
    #: own context — not a swap of the main loop's model, which would invalidate
    #: the prompt cache for more than it saves.
    summariser: ModelClient | None = None


@dataclass
class RunResult:
    run_id: str
    text: str
    messages: list[dict[str, Any]]
    stop_reason: str | None
    iterations: int
    spend_usd: float
    usage: Usage = field(default_factory=Usage)
    truncated_by: str | None = None  # which cap ended the run, if any


async def run_harness(
    *,
    deps: HarnessDeps,
    user_id: str,
    session_id: str,
    run_id: str,
    user_message: str | None = None,
    turn_context: dict[str, Any] | None = None,
    history: list[dict[str, Any]] | None = None,
    scratch: dict[str, Any] | None = None,
    emitter: EventEmitter | None = None,
) -> RunResult:
    """Drive one run to completion.

    Pass ``user_message`` to start or continue a conversation. Pass only
    ``history`` (with no ``user_message``) to resume a run that was interrupted
    — the loop picks up from whatever state the persisted history is in.
    """
    emit = emitter or EventEmitter(run_id)
    budget = RunBudget(caps=deps.caps)
    messages: list[dict[str, Any]] = list(history or [])
    scratch = dict(scratch or {})

    ctx = ToolContext(
        user_id=user_id,
        session_id=session_id,
        run_id=run_id,
        sandbox=deps.sandbox,
        max_output_chars=deps.caps.max_tool_output_chars,
        timeout_s=deps.caps.tool_timeout_s,
        scratch=scratch,
    )

    if user_message is not None:
        messages.append({"role": "user", "content": user_message})
        # Per-turn context goes here, inside `messages`, never in the system
        # prompt — that is what keeps the cached prefix byte-stable.
        if turn_context:
            messages.append(turn_context)

    await deps.store.set_status(user_id=user_id, run_id=run_id, status=RunStatus.RUNNING)
    await emit.emit(EventType.RUN_STARTED, session_id=session_id)

    tools = deps.registry.specs()
    system = deps.system_prompt.to_api()
    prefix_fingerprint = deps.system_prompt.fingerprint

    truncated_by: str | None = None
    last_stop: str | None = None
    final_text = ""

    try:
        while True:
            budget.begin_iteration()
            await emit.emit(
                EventType.TURN_STARTED, iteration=budget.iterations, **budget.snapshot()
            )

            messages = await _maybe_compact(deps, messages, emit, budget)

            # Cache-invalidation tripwire. If this ever fires, something
            # dynamic is being interpolated into the system prefix and the
            # cache-hit rate is silently zero.
            if deps.system_prompt.fingerprint != prefix_fingerprint:
                log.error(
                    "system prefix changed mid-run run=%s — prompt cache is being "
                    "invalidated every turn",
                    run_id,
                )
                prefix_fingerprint = deps.system_prompt.fingerprint

            _GREETINGS = {"hi", "hello", "hey", "good morning", "good afternoon", "good evening", "sup", "howdy", "hi there", "hello there"}
            last_user_msg = ""
            for m in reversed(messages):
                if m.get("role") == "user" and isinstance(m.get("content"), str):
                    last_user_msg = m["content"].strip().lower()
                    break

            active_tools = None if last_user_msg in _GREETINGS else tools

            response = await deps.model.complete(
                system=system,
                messages=messages,
                tools=active_tools,
                max_tokens=deps.caps.max_tokens_per_turn,
            )

            cost = budget.record(response.usage, response.model or deps.model.model)
            await emit.emit(
                EventType.USAGE,
                cost_usd=round(cost, 6),
                model=response.model or deps.model.model,
                **budget.snapshot(),
            )

            # Append the whole content block list, unmodified.
            messages.append({"role": "assistant", "content": response.content})
            await _persist(deps, user_id, run_id, messages, ctx.scratch, budget)

            if response.text:
                final_text = response.text
                await emit.emit(EventType.TEXT, text=response.text)

            last_stop = response.stop_reason

            # A server-side tool paused the turn. The assistant content is
            # already in history, so re-sending resumes it.
            if response.stop_reason == "pause_turn":
                continue

            tool_uses = response.tool_uses
            if not tool_uses:
                if response.stop_reason not in _TERMINAL_STOPS:
                    log.warning(
                        "unexpected stop_reason=%r with no tool_use run=%s",
                        response.stop_reason,
                        run_id,
                    )
                break

            results = await _execute_tools(deps, tool_uses, ctx, emit)

            # One user message carrying every result, in call order.
            messages.append({"role": "user", "content": results})
            await _persist(deps, user_id, run_id, messages, ctx.scratch, budget)

    except BudgetExceeded as exc:
        truncated_by = type(exc).__name__
        final_text = final_text or str(exc)
        log.info("run capped run=%s reason=%s", run_id, truncated_by)
        await _persist(deps, user_id, run_id, messages, ctx.scratch, budget)
        await deps.store.set_status(
            user_id=user_id, run_id=run_id, status=RunStatus.FAILED, error=str(exc)
        )
        await emit.emit(
            EventType.RUN_FAILED, reason=truncated_by, message=str(exc), **budget.snapshot()
        )
        return RunResult(
            run_id=run_id,
            text=final_text,
            messages=messages,
            stop_reason=last_stop,
            iterations=budget.iterations,
            spend_usd=budget.spend_usd,
            usage=budget.usage,
            truncated_by=truncated_by,
        )

    except Exception as exc:  # noqa: BLE001
        log.exception("run failed run=%s user=%s", run_id, user_id)
        # History is already persisted up to the last completed turn, so this
        # run is resumable rather than lost.
        await deps.store.set_status(
            user_id=user_id,
            run_id=run_id,
            status=RunStatus.FAILED,
            error=f"{type(exc).__name__}: {exc}",
        )
        await emit.emit(EventType.RUN_FAILED, reason=type(exc).__name__, message=str(exc))
        raise

    await deps.store.set_status(
        user_id=user_id, run_id=run_id, status=RunStatus.SUCCEEDED
    )
    await emit.emit(EventType.RUN_FINISHED, stop_reason=last_stop, **budget.snapshot())

    return RunResult(
        run_id=run_id,
        text=final_text,
        messages=messages,
        stop_reason=last_stop,
        iterations=budget.iterations,
        spend_usd=budget.spend_usd,
        usage=budget.usage,
    )


# --------------------------------------------------------------------------
# internals
# --------------------------------------------------------------------------


async def _execute_tools(
    deps: HarnessDeps,
    tool_uses: list[dict[str, Any]],
    ctx: ToolContext,
    emit: EventEmitter,
) -> list[dict[str, Any]]:
    """Run a batch of tool calls concurrently, preserving call order.

    `gather` preserves ordering, which matters: results are matched by
    `tool_use_id`, but keeping positional order too makes the transcript
    readable and the audit log deterministic.
    """
    coros = [_execute_one(deps, use, ctx, emit) for use in tool_uses]
    return list(await asyncio.gather(*coros))


async def _execute_one(
    deps: HarnessDeps,
    use: dict[str, Any],
    ctx: ToolContext,
    emit: EventEmitter,
) -> dict[str, Any]:
    name = use.get("name", "")
    use_id = use.get("id", "")
    # `input` arrives already parsed by the SDK. Never string-match it.
    args = use.get("input")
    if not isinstance(args, dict):
        args = {}

    await emit.emit(EventType.TOOL_CALL, tool=name, tool_use_id=use_id, args=args)

    tool = deps.registry.get(name)
    mutates = bool(getattr(tool, "mutates", True))

    outcome = await deps.permissions.check(name, mutates, args, ctx)
    if outcome.decision is Decision.DENY:
        await emit.emit(
            EventType.TOOL_DENIED, tool=name, tool_use_id=use_id, reason=outcome.reason
        )
        return _tool_result_block(use_id, ToolResult.error(outcome.reason))

    short_circuit = await deps.hooks.run_pre(name, args, ctx)
    if short_circuit is not None:
        return _tool_result_block(use_id, short_circuit)

    result, duration = await deps.registry.execute(name, args, ctx)
    result = await deps.hooks.run_post(name, args, result, ctx, duration)

    await emit.emit(
        EventType.TOOL_RESULT,
        tool=name,
        tool_use_id=use_id,
        is_error=result.is_error,
        duration_s=round(duration, 3),
        preview=result.content[:500],
        todos=ctx.scratch.get(TODO_KEY) if name == "TodoWrite" else None,
    )
    return _tool_result_block(use_id, result)


def _tool_result_block(tool_use_id: str, result: ToolResult) -> dict[str, Any]:
    content = result.content
    if result.is_error:
        content += (
            "\n\n[STRUCTURED DEBUG TRIAGE INSTRUCTION]\n"
            "1. Localize: Identify the exact failing line or parameter from the error output above.\n"
            "2. Shift Strategy: Do NOT repeat the exact same broken code or tool parameters.\n"
            "3. Minimal Targeted Fix: Apply a specific fix (e.g. write a python script generator or correct syntax).\n"
            "4. Verify: Run a syntax or file integrity check before completing."
        )
    block: dict[str, Any] = {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": content,
    }
    if result.is_error:
        block["is_error"] = True
    return block


async def _maybe_compact(
    deps: HarnessDeps,
    messages: list[dict[str, Any]],
    emit: EventEmitter,
    budget: RunBudget,
) -> list[dict[str, Any]]:
    """Compact when the request is getting large.

    Uses the previous turn's reported input tokens rather than a token count
    call — it is one request cheaper and accurate enough for a threshold that
    sits well below the context limit on purpose.
    """
    if deps.summariser is None:
        return messages
    observed_input = budget.usage.total_input
    if observed_input < deps.caps.compact_at_input_tokens:
        return messages

    result = await compact(
        messages,
        summariser=deps.summariser,
        keep_recent_turns=deps.caps.compact_keep_recent_turns,
    )
    if result.compacted:
        await emit.emit(
            EventType.COMPACTED,
            summarised_messages=result.summarised_messages,
            input_tokens_before=observed_input,
        )
    return result.messages


async def _persist(
    deps: HarnessDeps,
    user_id: str,
    run_id: str,
    messages: list[dict[str, Any]],
    scratch: dict[str, Any],
    budget: RunBudget,
) -> None:
    await deps.store.save_messages(
        user_id=user_id,
        run_id=run_id,
        messages=messages,
        scratch=scratch,
        iterations=budget.iterations,
        spend_usd=budget.spend_usd,
    )

import logging
from dataclasses import replace
from typing import Any
from twin.harness import HarnessDeps, RunResult, run_harness
from twin.store.base import ConversationStore

log = logging.getLogger(__name__)


async def run_subagent(
    *,
    deps: HarnessDeps,
    user_id: str,
    parent_session_id: str,
    role: str,
    task_prompt: str,
    max_iterations: int = 3,
) -> str:
    """Execute a subagent task in an isolated session context.

    Subagents run with strict iteration caps to prevent runaway API spend.
    Returns the subagent's final output text.
    """
    sub_session_id = f"{parent_session_id}_sub_{role.replace(' ', '_').lower()}"
    run = await deps.store.create_run(user_id=user_id, session_id=sub_session_id)

    # Subagent budget caps
    sub_caps = replace(deps.caps, max_iterations=max_iterations)
    sub_deps = replace(deps, caps=sub_caps)

    log.info("Spawning subagent role=%s user=%s run_id=%s", role, user_id, run.id)

    result = await run_harness(
        deps=sub_deps,
        user_id=user_id,
        session_id=sub_session_id,
        run_id=run.id,
        user_message=f"You are a specialized subagent with role: '{role}'. Your task is:\n{task_prompt}",
        history=[],
    )

    return result.text.strip() or "Subagent completed task with no text output."

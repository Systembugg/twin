"""Worker process.

Pulls runs off the stream, executes the harness, publishes events, acks. Scale
horizontally: N workers, each with a bounded number of concurrent runs. The
concurrency knob that matters is `max_concurrent_runs` per worker — an agentic
run is mostly waiting on the API, so a single worker handles far more than one,
but each holds a sandbox, and sandboxes are the finite resource.

Reaching 50+ concurrent users is a matter of worker count, not loop speed.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import socket
import uuid
from dataclasses import dataclass
from typing import Any

from twin.config import Settings
from twin.events import EventEmitter, EventType
from twin.harness import HarnessDeps, RunResult, run_harness
from twin.hooks import HookRegistry, audit_hook
from twin.llm.factory import build_model_client, build_summariser
from twin.persona import Persona, build_system_prompt, SystemPrompt
from twin.runtime.queue import EventBus, QueuedRun, RunQueue
from twin.runtime.ratelimit import RateLimiter
from twin.sandbox.local import LocalSandboxFactory
from twin.store.base import RunStatus
from twin.tools.registry import default_registry
from twin.runtime.local_worker import append_audit_log

log = logging.getLogger(__name__)


@dataclass
class WorkerConfig:
    settings: Settings
    max_concurrent_runs: int = 8
    reclaim_every_s: float = 30.0
    name: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            self.name = f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"


class Worker:
    def __init__(
        self,
        *,
        config: WorkerConfig,
        store: Any,
        redis: Any,
        persona_loader: Any,
        sandbox_factory: Any = None,
    ) -> None:
        self.config = config
        self.store = store
        self.queue = RunQueue(redis)
        self.bus = EventBus(redis)
        self.limiter = RateLimiter(redis=redis, quota=config.settings.quota)
        self.persona_loader = persona_loader
        self.sandboxes = sandbox_factory or LocalSandboxFactory(
            config.settings.workspace_root
        )
        self._sem = asyncio.Semaphore(config.max_concurrent_runs)
        self._stopping = asyncio.Event()
        self._inflight: set[asyncio.Task[None]] = set()

    # -- lifecycle ----------------------------------------------------------

    def install_signal_handlers(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._stopping.set)

    async def run_forever(self) -> None:
        await self.queue.ensure_group()
        reclaimer = asyncio.create_task(self._reclaim_loop())
        log.info("worker %s started", self.config.name)

        try:
            while not self._stopping.is_set():
                batch = await self.queue.consume(self.config.name, block_ms=2000)
                for job in batch:
                    await self._sem.acquire()
                    task = asyncio.create_task(self._guarded(job))
                    self._inflight.add(task)
                    task.add_done_callback(self._inflight.discard)
        finally:
            reclaimer.cancel()
            # Drain rather than abandon: an abandoned run leaves a sandbox and
            # an unacked entry, and the entry gets reclaimed and re-run.
            if self._inflight:
                log.info("draining %d in-flight run(s)", len(self._inflight))
                await asyncio.gather(*self._inflight, return_exceptions=True)
            log.info("worker %s stopped", self.config.name)

    async def _reclaim_loop(self) -> None:
        while not self._stopping.is_set():
            await asyncio.sleep(self.config.reclaim_every_s)
            try:
                stalled = await self.queue.reclaim_stalled(self.config.name)
                for job in stalled:
                    log.warning("reclaiming stalled run=%s", job.run_id)
                    await self._sem.acquire()
                    task = asyncio.create_task(self._guarded(job, resumed=True))
                    self._inflight.add(task)
                    task.add_done_callback(self._inflight.discard)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("reclaim failed")

    async def _guarded(self, job: QueuedRun, *, resumed: bool = False) -> None:
        try:
            await self._execute(job, resumed=resumed)
        except Exception:  # noqa: BLE001
            log.exception("run crashed run=%s", job.run_id)
        finally:
            self._sem.release()

    # -- execution ----------------------------------------------------------

    async def _execute(self, job: QueuedRun, *, resumed: bool) -> None:
        settings = self.config.settings
        await self.limiter.acquire_slot(job.user_id)
        sandbox = None
        try:
            run = await self.store.get_run(user_id=job.user_id, run_id=job.run_id)
            if run is None:
                log.error("run not found or not owned run=%s user=%s", job.run_id, job.user_id)
                await self.queue.ack(job.entry_id)
                return
            if run.status in (RunStatus.SUCCEEDED, RunStatus.CANCELLED):
                await self.queue.ack(job.entry_id)
                return

            persona: Persona = await self.persona_loader(job.user_id)
            sandbox = await self.sandboxes.acquire(
                user_id=job.user_id, session_id=job.session_id
            )

            hooks = HookRegistry()
            hooks.on_post_tool_use(audit_hook(log))

            from twin.skills.manager import SkillManager
            user_prompt = ""
            for m in run.messages:
                if m.get("role") == "user":
                    content = m.get("content", "")
                    if isinstance(content, str):
                        user_prompt += content + " "
            skills_context = SkillManager().get_relevant_skills(user_prompt)
            base_sys = build_system_prompt(persona)
            base_text = base_sys.blocks[0]["text"] if base_sys.blocks else ""
            combined_text = f"{base_text}\n\n{skills_context}" if skills_context else base_text
            final_sys_prompt = SystemPrompt(blocks=[{"type": "text", "text": combined_text}])
            if skills_context:
                append_audit_log(job.user_id, "SKILL_INJECTED", "Loaded 4 Core Agentic Skills + Intent Skill Cheatsheets into prompt context.")
            else:
                append_audit_log(job.user_id, "SKILL_INJECTED", "Loaded 4 Core Agentic Skills into prompt context.")

            deps = HarnessDeps(
                model=build_model_client(settings),
                summariser=build_summariser(settings),
                registry=default_registry(),
                store=self.store,
                sandbox=sandbox,
                system_prompt=final_sys_prompt,
                caps=settings.caps,
                hooks=hooks,
            )

            # Resume the sequence where the previous attempt left off, so a
            # reconnecting client sees one monotonic stream across the restart.
            prior = await self.store.load_events(
                user_id=job.user_id, run_id=job.run_id
            )
            start_seq = max((e.seq for e in prior), default=0)
            emitter = EventEmitter(
                job.run_id, sink=self._sink(job.user_id), start_seq=start_seq
            )

            # A resumed run replays its persisted history and sends no new user
            # message — the history already contains it.
            session_history = await self.store.load_session_messages(
                user_id=job.user_id, session_id=job.session_id
            )
            result: RunResult = await run_harness(
                deps=deps,
                user_id=job.user_id,
                session_id=job.session_id,
                run_id=job.run_id,
                user_message=None if resumed else job.message,
                history=session_history if session_history else run.messages,
                scratch=run.scratch,
                emitter=emitter,
            )

            await self.limiter.record_tokens(
                job.user_id, job.run_id, _total_tokens(result)
            )
        finally:
            if sandbox is not None:
                # Idempotent by contract. An orphaned sandbox costs money
                # forever, so this runs on every path.
                try:
                    await sandbox.close()
                except Exception:  # noqa: BLE001
                    log.exception("sandbox close failed run=%s", job.run_id)
            await self.limiter.release_slot(job.user_id)
            await self.queue.ack(job.entry_id)

    def _sink(self, user_id: str) -> Any:
        async def _emit(event: Any) -> None:
            await self.bus.publish(event)
            from twin.runtime.local_worker import append_audit_log
            if event.type.value == "tool_call":
                tool_name = event.data.get("tool", "")
                args = event.data.get("args", {})
                detail = ""
                if tool_name == "Bash":
                    detail = f" | command: {args.get('command') or args.get('cmd') or ''}"
                elif tool_name in ("WriteFile", "ReadFile", "EditFile"):
                    detail = f" | file: {args.get('path') or args.get('file') or ''}"
                elif tool_name == "TodoWrite":
                    todos = args.get("todos", [])
                    detail = f" | Plan: {len(todos)} tasks"
                elif tool_name == "SearchKnowledge":
                    detail = f" | query: {args.get('query')}"
                append_audit_log(user_id, "TOOL_CALL", f"Executing [{tool_name}]{detail}")
            elif event.type.value == "tool_result":
                tool_name = event.data.get("tool", "")
                is_err = event.data.get("is_error", False)
                todos = event.data.get("todos")
                todo_str = ""
                if todos:
                    done_cnt = sum(1 for t in todos if t.get("status") == "completed")
                    todo_str = f" (Progress: {done_cnt}/{len(todos)} tasks completed)"
                append_audit_log(user_id, "TOOL_RESULT", f"[{tool_name}] -> {'ERROR' if is_err else 'SUCCESS'}{todo_str}")
            elif event.type.value == "run_finished":
                spend = event.data.get("spend_usd", 0.0)
                turns = event.data.get("iterations", 1)
                append_audit_log(user_id, "RUN_FINISHED", f"Completed run {event.run_id} in {turns} turns | Spend: ${spend:.4f}")

            try:
                await self.store.append_event(
                    user_id=user_id, run_id=event.run_id, event=event
                )
            except Exception:  # noqa: BLE001
                # The live stream is best-effort; never fail a run on telemetry.
                log.exception("event persist failed run=%s", event.run_id)

        return _emit


def _total_tokens(result: RunResult) -> int:
    """Tokens billed against the user's rolling hourly budget.

    Cache reads are counted at full weight here on purpose: the budget exists
    to bound blast radius, not to model cost.
    """
    return result.usage.total_input + result.usage.output_tokens


async def main() -> None:
    """Entrypoint: `python -m twin.runtime.worker`."""
    import redis.asyncio as aioredis

    logging.basicConfig(
        level=os.environ.get("TWIN_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    settings = Settings.from_env()
    if not settings.redis_url or not settings.database_url:
        raise SystemExit("TWIN_REDIS_URL and TWIN_DATABASE_URL are required for workers")

    from twin.runtime.personas import make_persona_loader
    from twin.store.postgres import PostgresStore

    store = await PostgresStore.connect(settings.database_url)
    redis = aioredis.from_url(settings.redis_url)

    worker = Worker(
        config=WorkerConfig(settings=settings),
        store=store,
        redis=redis,
        persona_loader=make_persona_loader(store),
    )
    worker.install_signal_handlers()
    await worker.run_forever()


if __name__ == "__main__":
    asyncio.run(main())

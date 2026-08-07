"""In-Memory Queue & Worker Execution Pool.

Processes queued user runs 1-by-1 sequentially to prevent Groq API rate limit overflow.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

from twin.config import Settings
from twin.events import Event, EventEmitter
from twin.harness import HarnessDeps, run_harness
from twin.hooks import HookRegistry, PermissionMode, PermissionPolicy
from twin.llm.factory import build_model_client, build_summariser
from twin.persona import build_system_prompt
from twin.runtime.personas import persona_from_row
from twin.sandbox.local import LocalSandboxFactory
from twin.store.base import RunStatus
from twin.tools.registry import default_registry

log = logging.getLogger(__name__)
LOG_PATH = Path(r"C:\tmp\twin-workspaces\audit_stream.log")

_QUEUE: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
_SEMAPHORE = asyncio.Semaphore(3)  # Allow 3 parallel workers concurrently!
_WORKER_TASK: asyncio.Task | None = None


def append_audit_log(user_id: str, event_type: str, message: str):
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] [{user_id.upper()}] [{event_type}] {message}\n"
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line)


async def enqueue_local_run(
    *, store: Any, settings: Settings, user_id: str, session_id: str, run_id: str, message: str
):
    global _WORKER_TASK
    if _WORKER_TASK is None or _WORKER_TASK.done():
        _WORKER_TASK = asyncio.create_task(_worker_loop(store, settings))

    append_audit_log(user_id, "QUEUE_ENQUEUE", f"Enqueued run {run_id} for user {user_id}")
    await _QUEUE.put(
        {
            "user_id": user_id,
            "session_id": session_id,
            "run_id": run_id,
            "message": message,
        }
    )


async def _worker_loop(store: Any, settings: Settings):
    sandbox_factory = LocalSandboxFactory(settings.workspace_root)
    log.info("Local worker loop started")

    while True:
        job = await _QUEUE.get()
        asyncio.create_task(_process_single_job(job, store, settings, sandbox_factory))

async def _process_single_job(job: dict[str, Any], store: Any, settings: Settings, sandbox_factory: LocalSandboxFactory):
    async with _SEMAPHORE:
        try:
            user_id = job["user_id"]
            session_id = job["session_id"]
            run_id = job["run_id"]
            message = job["message"]

            append_audit_log(user_id, "QUEUE_DEQUEUE", f"Processing run {run_id} from queue...")
            await store.set_status(user_id=user_id, run_id=run_id, status=RunStatus.RUNNING)

            sandbox = await sandbox_factory.acquire(user_id=user_id, session_id=session_id)
            persona = persona_from_row(user_id, {"name": f"Persona {user_id}", "summary": "Interactive User"})
            registry = default_registry(enable_subagents=False, enable_memory=False)

            deps = HarnessDeps(
                model=build_model_client(settings),
                summariser=build_summariser(settings),
                registry=registry,
                store=store,
                sandbox=sandbox,
                system_prompt=build_system_prompt(persona),
                caps=settings.caps,
                hooks=HookRegistry(),
                permissions=PermissionPolicy(PermissionMode.AUTO),
            )

            async def worker_sink(event: Event):
                if event.type.value == "tool_call":
                    tool_name = event.data.get("tool", "")
                    append_audit_log(user_id, "TOOL_CALL", f"Executing tool [{tool_name}]")
                elif event.type.value == "tool_result":
                    tool_name = event.data.get("tool", "")
                    is_err = event.data.get("is_error", False)
                    append_audit_log(user_id, "TOOL_RESULT", f"[{tool_name}] -> {'ERROR' if is_err else 'SUCCESS'}")

            try:
                history = await store.load_session_messages(user_id=user_id, session_id=session_id)
                result = await run_harness(
                    deps=deps,
                    user_id=user_id,
                    session_id=session_id,
                    run_id=run_id,
                    user_message=message,
                    history=history,
                    emitter=EventEmitter(run_id=run_id, sink=worker_sink),
                )
                await store.set_status(user_id=user_id, run_id=run_id, status=RunStatus.SUCCEEDED)
                await store.save_messages(
                    user_id=user_id,
                    run_id=run_id,
                    messages=result.messages,
                    iterations=result.iterations,
                    spend_usd=result.spend_usd,
                )
                append_audit_log(
                    user_id,
                    "RUN_FINISHED",
                    f"Completed run {run_id} in {result.iterations} turns | Spend: ${result.spend_usd:.4f}",
                )
            except Exception as exc:
                log.exception("worker run execution failed run_id=%s", run_id)
                append_audit_log(user_id, "RUN_FAILED", f"Run {run_id} failed: {type(exc).__name__}: {exc}")
                await store.set_status(user_id=user_id, run_id=run_id, status=RunStatus.FAILED, error=str(exc))
            finally:
                await sandbox.close()

        except Exception as exc:
            log.exception("worker job failed unexpectedly")
            append_audit_log(job.get("user_id", "UNKNOWN"), "WORKER_ERROR", f"Job failed: {exc}")
        finally:
            _QUEUE.task_done()

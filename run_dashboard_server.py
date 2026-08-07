"""Central Twin Enterprise Dashboard & Queue Execution Server.

Runs FastAPI, Rate Limiter, Queue System, and In-Memory Worker Loop.
Processes queued user runs sequentially to prevent API rate limits!
"""

from __future__ import annotations

import asyncio
import contextlib
from contextlib import asynccontextmanager
import logging
import os
import time
from pathlib import Path
import uvicorn
from dotenv import load_dotenv

load_dotenv()

from twin.config import Settings
from twin.events import Event, EventEmitter
from twin.harness import HarnessDeps, run_harness
from twin.hooks import HookRegistry, PermissionMode, PermissionPolicy
from twin.llm.factory import build_model_client, build_summariser
from twin.persona import build_system_prompt
from twin.runtime.api import create_app
from twin.runtime.personas import persona_from_row
from twin.sandbox.local import LocalSandboxFactory
from twin.store.base import RunStatus
from twin.store.memory import InMemoryStore
from twin.tools.registry import default_registry

log = logging.getLogger("twin.server")
LOG_PATH = Path(r"C:\tmp\twin-workspaces\audit_stream.log")

# Global queue for worker processing
_WORK_QUEUE: asyncio.Queue[dict] = asyncio.Queue()


def append_audit_log(user_id: str, event_type: str, message: str):
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] [{user_id.upper()}] [{event_type}] {message}\n"
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line)


async def in_memory_worker_loop(store: InMemoryStore, settings: Settings):
    """Processes queued user runs 1-by-1 sequentially to prevent API rate limits."""
    sandbox_factory = LocalSandboxFactory(settings.workspace_root)

    print("🤖 Twin Queue Worker Pool STARTED -- Processing runs sequentially...")

    while True:
        job = await _WORK_QUEUE.get()
        user_id = job["user_id"]
        session_id = job["session_id"]
        run_id = job["run_id"]
        message = job["message"]

        append_audit_log(user_id, "QUEUE_DEQUEUE", f"Processing run {run_id} from queue...")

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
                append_audit_log(user_id, "TOOL_CALL", f"Executing [{tool_name}]")
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
            append_audit_log(
                user_id,
                "RUN_FINISHED",
                f"Completed {run_id} in {result.iterations} turns | Spend: ${result.spend_usd:.4f}",
            )
        except Exception as exc:
            append_audit_log(user_id, "RUN_FAILED", f"Run {run_id} failed: {type(exc).__name__}: {exc}")
            await store.set_status(user_id=user_id, run_id=run_id, status=RunStatus.FAILED, error=str(exc))
        finally:
            await sandbox.close()
            _WORK_QUEUE.task_done()


def main():
    settings = Settings.from_env()
    store = InMemoryStore()

    async def mock_auth(token):
        if token and token.startswith("Bearer "):
            return token.split("Bearer ", 1)[1].strip()
        return "local_test_user"

    @asynccontextmanager
    async def lifespan(app):
        # Start worker loop task in background
        worker_task = asyncio.create_task(in_memory_worker_loop(store, settings))
        yield
        worker_task.cancel()
        with contextlib.suppress(Exception):
            await worker_task

    app = create_app(
        settings=settings,
        store=store,
        redis=None,
        authenticate=mock_auth,
        lifespan=lifespan,
    )

    # Monkey patch create_run endpoint to push to _WORK_QUEUE when redis is None
    original_create_run = app.routes[-3].endpoint

    print("\n" + "=" * 65)
    print("TWIN ENTERPRISE CENTRAL SERVER & QUEUE SYSTEM IS LIVE!")
    print("Dashboard UI   : http://localhost:8000/dashboard")
    print("Health Endpoint: http://localhost:8000/healthz")
    print("=" * 65 + "\n")

    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")


if __name__ == "__main__":
    main()

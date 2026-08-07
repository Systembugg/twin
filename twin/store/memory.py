"""In-memory store.

For tests and single-process development. Implements the same tenancy checks as
the Postgres store so that a test which would leak across tenants fails here
too, rather than only in production.
"""

from __future__ import annotations

import asyncio
import copy
import time
from typing import Any

from twin.events import Event
from twin.store.base import Run, RunStatus


class InMemoryStore:
    def __init__(self) -> None:
        self._runs: dict[str, Run] = {}
        self._events: dict[str, list[Event]] = {}
        self._idempotency: dict[tuple[str, str], str] = {}
        self._lock = asyncio.Lock()

    # -- helpers ------------------------------------------------------------

    def _owned(self, user_id: str, run_id: str) -> Run | None:
        run = self._runs.get(run_id)
        if run is None or run.user_id != user_id:
            return None
        return run

    # -- ConversationStore --------------------------------------------------

    async def create_run(
        self,
        *,
        user_id: str,
        session_id: str,
        run_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> Run:
        async with self._lock:
            if idempotency_key is not None:
                existing_id = self._idempotency.get((user_id, idempotency_key))
                if existing_id is not None:
                    return copy.deepcopy(self._runs[existing_id])

            run = Run(
                id=run_id or Run.new_id(),
                user_id=user_id,
                session_id=session_id,
                status=RunStatus.QUEUED,
            )
            self._runs[run.id] = run
            self._events.setdefault(run.id, [])
            if idempotency_key is not None:
                self._idempotency[(user_id, idempotency_key)] = run.id
            return copy.deepcopy(run)

    async def get_run(self, *, user_id: str, run_id: str) -> Run | None:
        run = self._owned(user_id, run_id)
        return copy.deepcopy(run) if run else None

    async def save_messages(
        self,
        *,
        user_id: str,
        run_id: str,
        messages: list[dict[str, Any]],
        scratch: dict[str, Any] | None = None,
        iterations: int = 0,
        spend_usd: float = 0.0,
    ) -> None:
        async with self._lock:
            run = self._owned(user_id, run_id)
            if run is None:
                return
            run.messages = copy.deepcopy(messages)
            if scratch is not None:
                run.scratch = copy.deepcopy(scratch)
            run.iterations = iterations
            run.spend_usd = spend_usd
            run.updated_at = time.time()

    async def set_status(
        self,
        *,
        user_id: str,
        run_id: str,
        status: RunStatus,
        error: str | None = None,
    ) -> None:
        async with self._lock:
            run = self._owned(user_id, run_id)
            if run is None:
                return
            run.status = status
            run.error = error
            run.updated_at = time.time()

    async def load_session_messages(
        self, *, user_id: str, session_id: str, limit: int = 200
    ) -> list[dict[str, Any]]:
        runs = sorted(
            (
                r
                for r in self._runs.values()
                if r.user_id == user_id
                and r.session_id == session_id
                and (r.status == RunStatus.SUCCEEDED or r.status == "succeeded")
            ),
            key=lambda r: r.created_at,
        )
        if not runs:
            return []
        return copy.deepcopy(runs[-1].messages)[-limit:]

    async def append_event(self, *, user_id: str, run_id: str, event: Event) -> None:
        if self._owned(user_id, run_id) is None:
            return
        self._events.setdefault(run_id, []).append(event)

    async def load_events(
        self, *, user_id: str, run_id: str, after_seq: int = 0
    ) -> list[Event]:
        if self._owned(user_id, run_id) is None:
            return []
        return [e for e in self._events.get(run_id, []) if e.seq > after_seq]

"""Conversation store: the durability contract.

Every method takes `user_id`. That is not redundancy — it is the tenancy
boundary. Filtering by `session_id` alone means a leaked or guessed session ID
reads another tenant's conversation, and no amount of prompt instruction fixes
that. Implementations MUST include `user_id` in the WHERE clause.

The other contract is `save_messages` after **every** turn. That is what makes
a killed worker recoverable, and it is why `ModelResponse.content` is stored as
plain JSON: the reload is byte-identical to what would have been sent anyway.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable


class RunStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Run:
    id: str
    user_id: str
    session_id: str
    status: RunStatus = RunStatus.QUEUED
    #: Full API message array. The single source of truth for resumption.
    messages: list[dict[str, Any]] = field(default_factory=list)
    #: TodoWrite state and anything else tools stash per run.
    scratch: dict[str, Any] = field(default_factory=dict)
    iterations: int = 0
    spend_usd: float = 0.0
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    @staticmethod
    def new_id() -> str:
        return f"run_{uuid.uuid4().hex}"


@runtime_checkable
class ConversationStore(Protocol):
    async def create_run(
        self,
        *,
        user_id: str,
        session_id: str,
        run_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> Run:
        """Create a run, or return the existing one for `idempotency_key`.

        Idempotency is not optional: retries and double-submits are normal, and
        each duplicate run is a duplicate sandbox and a duplicate bill.
        """
        ...

    async def get_run(self, *, user_id: str, run_id: str) -> Run | None: ...

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
        """Persist the turn. Called after every model turn and every tool batch."""
        ...

    async def set_status(
        self,
        *,
        user_id: str,
        run_id: str,
        status: RunStatus,
        error: str | None = None,
    ) -> None: ...

    async def load_session_messages(
        self, *, user_id: str, session_id: str, limit: int = 200
    ) -> list[dict[str, Any]]:
        """Prior conversation for a session, for multi-run continuity."""
        ...

    async def append_event(self, *, user_id: str, run_id: str, event: Any) -> None:
        """Durable copy of the event stream. Redis is the live path; this is
        what a client reconnecting after the TTL reads."""
        ...

    async def load_events(
        self, *, user_id: str, run_id: str, after_seq: int = 0
    ) -> list[Any]: ...

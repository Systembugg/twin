"""Sandbox protocol.

This is the seam that keeps the execution backend swappable. `LocalSandbox` is
the development implementation; a leased E2B/Modal container or a Managed
Agents session implements the same five methods and nothing above this layer
changes.

Deliberate constraint: **the harness never touches this interface.** Only tool
implementations do. That is what makes the swap a configuration change rather
than a refactor.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class ExecResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False
    truncated: bool = False


@runtime_checkable
class Sandbox(Protocol):
    """A per-session, isolated filesystem + process namespace."""

    session_id: str

    async def read_file(self, path: str) -> str: ...

    async def write_file(self, path: str, content: str) -> int:
        """Returns bytes written."""
        ...

    async def list_dir(self, path: str) -> list[str]: ...

    async def exec(self, command: str, timeout_s: float) -> ExecResult: ...

    async def close(self) -> None:
        """Release the sandbox. Must be idempotent — cleanup runs on both the
        happy path and the crash path, and orphaned sandboxes cost money."""
        ...


@runtime_checkable
class SandboxFactory(Protocol):
    async def acquire(self, *, user_id: str, session_id: str) -> Sandbox:
        """Lease a sandbox for a session.

        Implementations MUST scope by ``user_id`` as well as ``session_id``.
        A session ID alone is a guessable identifier; tenancy is enforced here,
        not in the prompt.
        """
        ...

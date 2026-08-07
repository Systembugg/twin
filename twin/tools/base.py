"""Tool protocol and execution context.

Two rules that the rest of the system depends on:

1. A tool **returns** `ToolResult(is_error=True)` on failure. It does not raise
   through the loop. An exception-based tool layer cannot be made resumable,
   because the run dies between the `tool_use` and its `tool_result` and the
   persisted history is left in an unsendable state.
2. A tool's `description` says *when to call it*, not just what it does. That
   phrasing measurably improves how reliably the model reaches for it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from twin.sandbox.base import Sandbox


@dataclass
class ToolContext:
    """Everything a tool is allowed to know.

    Tenancy is passed explicitly rather than read from a global, so a tool
    physically cannot act outside the caller's tenant.
    """

    user_id: str
    session_id: str
    run_id: str
    sandbox: Sandbox
    max_output_chars: int = 30_000
    timeout_s: float = 120.0
    #: Scratch space shared across tools within one run (TodoWrite uses it).
    scratch: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResult:
    content: str
    is_error: bool = False

    def truncated_to(self, limit: int) -> ToolResult:
        if len(self.content) <= limit:
            return self
        head = self.content[: limit - 200]
        omitted = len(self.content) - len(head)
        return ToolResult(
            content=f"{head}\n\n[... {omitted} characters truncated ...]",
            is_error=self.is_error,
        )

    @classmethod
    def error(cls, message: str) -> ToolResult:
        return cls(content=message, is_error=True)


@runtime_checkable
class Tool(Protocol):
    name: str
    description: str
    input_schema: dict[str, Any]
    #: Tools that change state need an approval gate in "ask" permission mode.
    mutates: bool

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult: ...


class BaseTool:
    """Convenience base. Subclasses set the class attributes and implement `run`."""

    name: str = ""
    description: str = ""
    input_schema: dict[str, Any] = {}
    mutates: bool = False

    def spec(self) -> dict[str, Any]:
        """The wire format sent to the API."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        raise NotImplementedError

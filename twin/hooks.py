"""Permission modes and lifecycle hooks.

At production scale these stop being a nicety. `PreToolUse` is where the
approval gate, the per-tool rate limit, and the "this argument looks like an
exfiltration attempt" check live; `PostToolUse` is where the audit record and
the cost meter live. Both are seams, not policy — the policy is injected.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Awaitable, Callable, Protocol

from twin.tools.base import ToolContext, ToolResult

log = logging.getLogger(__name__)


class PermissionMode(str, Enum):
    AUTO = "auto"  # run everything the toolset allows
    ASK = "ask"  # mutating tools require approval
    DENY = "deny"  # read-only; mutations are refused


class Decision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"


@dataclass
class PermissionOutcome:
    decision: Decision
    reason: str = ""


ApprovalCallback = Callable[[str, dict[str, Any], ToolContext], Awaitable[bool]]


class PermissionPolicy:
    """Resolves whether a tool call may proceed.

    In ASK mode the decision is delegated to `approve`, an async callback the
    deployment supplies — in the API it resolves against a pending-approval
    record the user answers over the event stream; in the CLI it is a prompt.
    A missing callback in ASK mode denies rather than allows, because failing
    open on an approval gate is not a real gate.
    """

    def __init__(
        self,
        mode: PermissionMode = PermissionMode.AUTO,
        *,
        approve: ApprovalCallback | None = None,
        always_allow: frozenset[str] = frozenset(),
        always_deny: frozenset[str] = frozenset(),
    ) -> None:
        self.mode = mode
        self.approve = approve
        self.always_allow = always_allow
        self.always_deny = always_deny

    async def check(
        self, tool_name: str, mutates: bool, args: dict[str, Any], ctx: ToolContext
    ) -> PermissionOutcome:
        if tool_name in self.always_deny:
            return PermissionOutcome(Decision.DENY, f"{tool_name} is disabled for this user.")
        if tool_name in self.always_allow or not mutates:
            return PermissionOutcome(Decision.ALLOW)

        if self.mode is PermissionMode.AUTO:
            return PermissionOutcome(Decision.ALLOW)
        if self.mode is PermissionMode.DENY:
            return PermissionOutcome(
                Decision.DENY,
                f"{tool_name} makes changes and this session is read-only.",
            )

        if self.approve is None:
            return PermissionOutcome(
                Decision.DENY,
                f"{tool_name} requires approval but no approver is configured.",
            )
        approved = await self.approve(tool_name, args, ctx)
        return PermissionOutcome(
            Decision.ALLOW if approved else Decision.DENY,
            "" if approved else f"The user declined the {tool_name} call.",
        )


class PreToolUseHook(Protocol):
    async def __call__(
        self, tool_name: str, args: dict[str, Any], ctx: ToolContext
    ) -> ToolResult | None:
        """Return a `ToolResult` to short-circuit, or None to proceed."""
        ...


class PostToolUseHook(Protocol):
    async def __call__(
        self,
        tool_name: str,
        args: dict[str, Any],
        result: ToolResult,
        ctx: ToolContext,
        duration_s: float,
    ) -> ToolResult:
        """Return the result, possibly modified."""
        ...


class HookRegistry:
    def __init__(self) -> None:
        self._pre: list[PreToolUseHook] = []
        self._post: list[PostToolUseHook] = []

    def on_pre_tool_use(self, hook: PreToolUseHook) -> None:
        self._pre.append(hook)

    def on_post_tool_use(self, hook: PostToolUseHook) -> None:
        self._post.append(hook)

    async def run_pre(
        self, tool_name: str, args: dict[str, Any], ctx: ToolContext
    ) -> ToolResult | None:
        for hook in self._pre:
            try:
                short_circuit = await hook(tool_name, args, ctx)
            except Exception:  # noqa: BLE001
                log.exception("pre_tool_use hook failed tool=%s", tool_name)
                continue
            if short_circuit is not None:
                return short_circuit
        return None

    async def run_post(
        self,
        tool_name: str,
        args: dict[str, Any],
        result: ToolResult,
        ctx: ToolContext,
        duration_s: float,
    ) -> ToolResult:
        for hook in self._post:
            try:
                result = await hook(tool_name, args, result, ctx, duration_s)
            except Exception:  # noqa: BLE001
                # A broken observability hook must never fail the run.
                log.exception("post_tool_use hook failed tool=%s", tool_name)
        return result


def audit_hook(logger: logging.Logger | None = None) -> PostToolUseHook:
    """Structured per-call audit record. Register this in every deployment."""
    target = logger or log

    async def _hook(
        tool_name: str,
        args: dict[str, Any],
        result: ToolResult,
        ctx: ToolContext,
        duration_s: float,
    ) -> ToolResult:
        target.info(
            "tool_call",
            extra={
                "tool": tool_name,
                "user_id": ctx.user_id,
                "session_id": ctx.session_id,
                "run_id": ctx.run_id,
                "duration_s": round(duration_s, 3),
                "is_error": result.is_error,
                "result_chars": len(result.content),
            },
        )
        return result

    return _hook

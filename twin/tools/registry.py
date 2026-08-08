"""Tool registry.

The registry owns two things the loop must not have to think about:

* **Deterministic ordering.** `specs()` returns tools in registration order,
  always. The tool block is the first thing in the cached prefix, so a set that
  reorders between requests silently destroys every cache hit downstream of it.
* **Exception containment.** `execute()` converts any exception — including
  ones the tool author did not anticipate — into an error `ToolResult`. This is
  the single place that guarantee is enforced.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from twin.errors import ToolExecutionError
from twin.tools.base import BaseTool, ToolContext, ToolResult

log = logging.getLogger(__name__)


class ToolRegistry:
    def __init__(self, tools: list[BaseTool] | None = None) -> None:
        self._tools: dict[str, BaseTool] = {}
        for tool in tools or []:
            self.register(tool)

    def register(self, tool: BaseTool) -> None:
        if not tool.name:
            raise ValueError(f"{type(tool).__name__} has no name")
        if tool.name in self._tools:
            raise ValueError(f"Duplicate tool name: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools)

    def specs(self) -> list[dict[str, Any]]:
        """Tool definitions in stable registration order."""
        return [t.spec() for t in self._tools.values()]

    async def execute(
        self, name: str, args: dict[str, Any], ctx: ToolContext
    ) -> tuple[ToolResult, float]:
        """Run a tool. Never raises. Returns (result, duration_seconds)."""
        started = time.monotonic()
        tool = self._tools.get(name)
        if tool is None:
            available = ", ".join(sorted(self._tools)) or "(none)"
            return (
                ToolResult.error(
                    f"Unknown tool {name!r}. Available tools: {available}."
                ),
                0.0,
            )

        try:
            result = await asyncio.wait_for(
                tool.run(args, ctx), timeout=ctx.timeout_s
            )
        except asyncio.TimeoutError:
            result = ToolResult.error(
                f"{name} exceeded the {ctx.timeout_s:.0f}s tool timeout and was "
                f"cancelled. Try a narrower operation."
            )
        except ToolExecutionError as exc:
            # Expected, recoverable failure — the model gets the message.
            result = ToolResult.error(str(exc))
        except Exception as exc:  # noqa: BLE001 - containment is the point
            log.exception(
                "tool crashed name=%s run=%s user=%s", name, ctx.run_id, ctx.user_id
            )
            # Do not leak internals to the model; log the detail, return a class.
            result = ToolResult.error(
                f"{name} failed with an internal error ({type(exc).__name__}). "
                f"Do not retry the identical call."
            )

        return result.truncated_to(ctx.max_output_chars), time.monotonic() - started


def default_registry(
    enable_subagents: bool = False, enable_memory: bool = False
) -> ToolRegistry:
    """The standard toolset.

    Deliberately small. Separate read/write/edit tools rather than one generic
    file tool: narrower schemas mean the model picks correctly more often, and
    the audit log becomes readable.
    """
    from twin.tools.filesystem import EditFile, ListDir, ReadFile, WriteFile
    from twin.tools.search_knowledge import SearchKnowledge
    from twin.tools.shell import Bash
    from twin.tools.todo import TodoWrite
    from twin.tools.web_search import WebSearch

    tools: list[BaseTool] = [
        ReadFile(),
        WriteFile(),
        EditFile(),
        ListDir(),
        Bash(),
        TodoWrite(),
        WebSearch(),
        SearchKnowledge(),
    ]

    if enable_subagents:
        from twin.tools.subagent import InvokeSubagent

        tools.append(InvokeSubagent())

    if enable_memory:
        from twin.tools.memory import SaveMemory, SearchMemory

        tools.extend([SearchMemory(), SaveMemory()])

    return ToolRegistry(tools)

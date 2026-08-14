"""SubAgent spawning tool.

Lets the main agent delegate subtasks to independent child agents that run
their own harness loops concurrently. Each child gets its own context but
shares the same sandbox (workspace directory).
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

from twin.tools.base import BaseTool, ToolContext, ToolResult

log = logging.getLogger(__name__)


class SubAgentSpawn(BaseTool):
    """Spawn one or more child agents to handle subtasks in parallel."""

    name = "SubAgentSpawn"
    description = (
        "Spawn parallel sub-agents to handle independent subtasks concurrently. "
        "Each sub-agent runs its own reasoning loop with full tool access. "
        "Use this when a task has multiple independent parts that can run simultaneously. "
        "Example: researching a topic while simultaneously writing code and generating docs.\n\n"
        "WHEN TO USE:\n"
        "- Task has 2+ independent subtasks that don't depend on each other's output\n"
        "- You need to research multiple topics simultaneously\n"
        "- You need to generate multiple files at once\n\n"
        "WHEN NOT TO USE:\n"
        "- Subtasks are sequential (B depends on A's output)\n"
        "- Task is simple enough for a single agent\n"
        "- Only 1 subtask exists"
    )
    input_schema = {
        "type": "object",
        "properties": {
            "subtasks": {
                "type": "array",
                "description": "List of subtask objects to execute in parallel",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "Short unique ID for this subtask (e.g. 'research', 'codegen', 'docs')"
                        },
                        "prompt": {
                            "type": "string",
                            "description": "The full instruction for the child agent. Be specific and self-contained."
                        },
                        "max_iterations": {
                            "type": "integer",
                            "description": "Max reasoning turns for this subtask. Default: 10",
                            "default": 10
                        }
                    },
                    "required": ["id", "prompt"]
                },
                "minItems": 1,
                "maxItems": 5
            }
        },
        "required": ["subtasks"]
    }
    mutates = True

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        subtasks = args.get("subtasks", [])
        if not subtasks:
            return ToolResult.error("No subtasks provided")
        if len(subtasks) > 5:
            return ToolResult.error("Maximum 5 concurrent subtasks allowed")

        # Import here to avoid circular deps
        from twin.tools.subagent_runner import run_subagents

        try:
            results = await run_subagents(subtasks, ctx)
            # Format results for the parent agent
            output_parts = []
            for r in results:
                status = "✅ SUCCESS" if not r["error"] else "❌ FAILED"
                output_parts.append(
                    f"--- Subtask [{r['id']}] {status} ---\n"
                    f"Iterations: {r['iterations']}\n"
                    f"Result:\n{r['output']}\n"
                )
            return ToolResult(content="\n".join(output_parts))
        except Exception as e:
            log.exception("SubAgentSpawn failed")
            return ToolResult.error(f"SubAgent execution failed: {e}")

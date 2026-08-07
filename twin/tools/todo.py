"""TodoWrite — an externalised task checklist.

Two reasons this exists on a production harness rather than only in a CLI:
the model keeps its plan in a place that survives compaction, and the user gets
a live progress view that is far more legible than streamed prose.

The list lives in `ToolContext.scratch`, so the harness can persist and replay
it alongside the message history.
"""

from __future__ import annotations

from typing import Any

from twin.tools.base import BaseTool, ToolContext, ToolResult

SCRATCH_KEY = "todos"
_STATUSES = ("pending", "in_progress", "completed")
_MARKS = {"pending": "[ ]", "in_progress": "[~]", "completed": "[x]"}


class TodoWrite(BaseTool):
    name = "TodoWrite"
    description = (
        "Record or update your task checklist. Call this at the start of any "
        "task that takes more than two steps, and again each time you finish a "
        "step. Send the complete list every time — it replaces the previous "
        "one. Keep exactly one item in_progress."
    )
    mutates = False
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "todos": {
                "type": "array",
                "description": "The full checklist, in order.",
                "items": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string", "description": "What needs doing."},
                        "status": {"type": "string", "enum": list(_STATUSES)},
                    },
                    "required": ["content", "status"],
                },
            }
        },
        "required": ["todos"],
    }

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        raw = args.get("todos")
        if not isinstance(raw, list):
            return ToolResult.error("todos must be an array.")

        todos: list[dict[str, str]] = []
        for i, item in enumerate(raw):
            if not isinstance(item, dict):
                return ToolResult.error(f"todos[{i}] is not an object.")
            content = str(item.get("content", "")).strip()
            status = str(item.get("status", "")).strip()
            if not content:
                return ToolResult.error(f"todos[{i}].content is empty.")
            if status not in _STATUSES:
                return ToolResult.error(
                    f"todos[{i}].status must be one of {', '.join(_STATUSES)}."
                )
            todos.append({"content": content, "status": status})

        in_progress = sum(1 for t in todos if t["status"] == "in_progress")
        ctx.scratch[SCRATCH_KEY] = todos

        rendered = "\n".join(f"{_MARKS[t['status']]} {t['content']}" for t in todos)
        note = ""
        if in_progress > 1:
            note = "\n\nNote: more than one item is in_progress. Keep exactly one."
        return ToolResult(rendered + note)

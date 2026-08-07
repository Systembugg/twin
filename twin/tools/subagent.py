from typing import Any
from twin.tools.base import BaseTool, ToolContext, ToolResult


class InvokeSubagent(BaseTool):
    name = "invoke_subagent"
    description = (
        "Delegate a research, analysis, or modular sub-task to an autonomous subagent. "
        "The subagent runs in a separate context with budget caps and returns a summary."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "role": {
                "type": "string",
                "description": "Role name for the subagent (e.g., 'Code Auditor', 'Documentation Researcher').",
            },
            "prompt": {
                "type": "string",
                "description": "Clear instructions for the subagent task.",
            },
        },
        "required": ["role", "prompt"],
    }
    mutates = True

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        role = args.get("role", "Assistant").strip()
        prompt = args.get("prompt", "").strip()

        if not prompt:
            return ToolResult.error("Subagent prompt cannot be empty.")

        # In-context subagent execution check
        subagent_runner = ctx.scratch.get("subagent_runner")
        if subagent_runner is None:
            return ToolResult.error("Subagent execution is disabled for this session.")

        try:
            summary = await subagent_runner(
                user_id=ctx.user_id,
                parent_session_id=ctx.session_id,
                role=role,
                task_prompt=prompt,
            )
            return ToolResult(content=f"Subagent '{role}' Completed Task:\n{summary}")
        except Exception as e:
            return ToolResult.error(f"Subagent execution failed: {str(e)}")

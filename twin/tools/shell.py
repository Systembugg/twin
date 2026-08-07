"""Bash tool.

Runs inside the session's sandbox with a minimal environment. The environment
is minimal on purpose: anything the process can read, the model can put into a
tool result, and anything in a tool result can be exfiltrated by a prompt
injection in a file the agent was asked to read. Credentials belong in
host-side tools, never in the sandbox environment.
"""

from __future__ import annotations

from typing import Any

from twin.tools.base import BaseTool, ToolContext, ToolResult


class Bash(BaseTool):
    name = "Bash"
    description = (
        "Run a shell command in the workspace. Prefer dedicated tools (ReadFile, WriteFile, EditFile) "
        "over Bash for file reading, writing, or editing. Do NOT use Bash for 'cat' or 'echo' file creation. "
        "Use WriteFile to write Python scripts first, then execute them via 'python script.py' in Bash. "
        "On Windows, use standard commands ('python script.py', 'pip install package'). Quote paths containing spaces."
    )
    mutates = True
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "The shell command to run."},
        },
        "required": ["command"],
    }

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        command = (args.get("command") or "").strip()
        if not command:
            return ToolResult.error("command was empty.")

        # Clamp to the run's ceiling — the model does not get to raise its own limit.
        requested = float(args.get("timeout_s") or ctx.timeout_s)
        timeout_s = min(requested, ctx.timeout_s)

        result = await ctx.sandbox.exec(command, timeout_s=timeout_s)

        parts: list[str] = []
        if result.stdout:
            parts.append(result.stdout.rstrip())
        if result.stderr:
            parts.append(f"[stderr]\n{result.stderr.rstrip()}")
        if result.truncated:
            parts.append("[output truncated]")

        body = "\n".join(parts) if parts else "(no output)"

        if result.timed_out:
            return ToolResult.error(body)
        if result.exit_code != 0:
            # A non-zero exit is information, not a crash — flag it so the model
            # reliably notices, but keep the full output.
            return ToolResult.error(f"exit code {result.exit_code}\n{body}")
        return ToolResult(body)

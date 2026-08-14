"""File tools: ReadFile, WriteFile, EditFile, ListDir.

Split rather than generic, on purpose. `EditFile` requires a unique match for
the text being replaced — an ambiguous edit is refused rather than guessed,
which is the difference between a model that corrects itself and one that
silently corrupts a file.
"""

from __future__ import annotations

from typing import Any

from twin.tools.base import BaseTool, ToolContext, ToolResult

_MAX_READ_LINES = 2000


class ReadFile(BaseTool):
    name = "ReadFile"
    description = (
        "Read a text file from the workspace. Call this whenever you need the "
        "current contents of a file — before editing it, to check your work "
        "after writing it, or when the user refers to a file you have not read "
        "yet. Never guess at file contents; read them."
    )
    mutates = False
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path relative to the workspace root.",
            },
            "offset": {
                "type": "integer",
                "description": "1-indexed line to start from. Omit to read from the top.",
            },
            "limit": {
                "type": "integer",
                "description": f"Max lines to return (default {_MAX_READ_LINES}).",
            },
        },
        "required": ["path"],
    }

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        path = args.get("path")
        if not path:
            return ToolResult.error("ReadFile requires a 'path' parameter.")

        text = await ctx.sandbox.read_file(path)
        lines = text.splitlines()
        if not lines:
            return ToolResult(f"{path} is an empty file (0 bytes).")

        offset = max(1, int(args.get("offset") or 1))
        limit = int(args.get("limit") or _MAX_READ_LINES)
        window = lines[offset - 1 : offset - 1 + limit]

        if not window:
            return ToolResult(f"{path} has {len(lines)} lines; offset {offset} is past the end.")

        numbered = "\n".join(
            f"{offset + i}\t{line}" for i, line in enumerate(window)
        )
        footer = ""
        if offset - 1 + len(window) < len(lines):
            footer = (
                f"\n\n[showing lines {offset}-{offset + len(window) - 1} "
                f"of {len(lines)}]"
            )
        return ToolResult(numbered + footer)


class WriteFile(BaseTool):
    name = "WriteFile"
    description = (
        "Create a new file, or completely replace an existing one. Intended primarily "
        "for NEW files. To modify an existing file, call EditFile instead to perform surgical "
        "replacements — WriteFile discards all previous file contents."
    )
    mutates = True
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path relative to the workspace root."},
            "content": {"type": "string", "description": "Full contents of the file."},
        },
        "required": ["path", "content"],
    }

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        path = args.get("path")
        content = args.get("content")
        if not path or content is None:
            return ToolResult.error(
                "WriteFile requires both 'path' (string) and 'content' (string) parameters. "
                "For multi-line files or complex code, you can also use the Bash tool with a heredoc (cat << 'EOF' > filename)."
            )

        written = await ctx.sandbox.write_file(path, content)
        return ToolResult(f"Wrote {written} bytes to {path}.")


class EditFile(BaseTool):
    name = "EditFile"
    description = (
        "Perform exact string replacements in an existing file. Call ReadFile first to inspect "
        "exact lines, indentation, and formatting before editing. old_string must appear "
        "exactly once — include unique surrounding lines. If it matches zero or multiple "
        "times, the edit is refused and nothing changes."
    )
    mutates = True
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path relative to the workspace root."},
            "old_string": {
                "type": "string",
                "description": "Exact text to replace, including indentation.",
            },
            "new_string": {"type": "string", "description": "Replacement text."},
            "replace_all": {
                "type": "boolean",
                "description": "Replace every occurrence instead of requiring uniqueness.",
            },
        },
        "required": ["path", "old_string", "new_string"],
    }

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        path = args.get("path")
        old = args.get("old_string")
        new = args.get("new_string")
        if not path or old is None or new is None:
            return ToolResult.error("EditFile requires 'path', 'old_string', and 'new_string' parameters.")

        replace_all = bool(args.get("replace_all"))

        if old == new:
            return ToolResult.error("old_string and new_string are identical; nothing to do.")

        text = await ctx.sandbox.read_file(path)
        count = text.count(old)

        if count == 0:
            return ToolResult.error(
                f"old_string was not found in {path}. Read the file again — it may "
                f"differ from what you expect (whitespace, indentation, or a stale copy)."
            )
        if count > 1 and not replace_all:
            return ToolResult.error(
                f"old_string appears {count} times in {path}. Include more "
                f"surrounding context to make it unique, or set replace_all: true."
            )

        updated = text.replace(old, new) if replace_all else text.replace(old, new, 1)
        await ctx.sandbox.write_file(path, updated)
        where = f"{count} occurrences" if replace_all else "1 occurrence"
        return ToolResult(f"Replaced {where} in {path}.")


class ListDir(BaseTool):
    name = "ListDir"
    description = (
        "List the entries of a directory in the workspace. Call this when you "
        "do not yet know what files exist — before guessing a filename, or to "
        "orient yourself at the start of a task. Directories are suffixed with /."
    )
    mutates = False
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Directory relative to the workspace root. Defaults to the root.",
            }
        },
        "required": [],
    }

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        path = args.get("path") or "."
        entries = await ctx.sandbox.list_dir(path)
        if not entries:
            return ToolResult(f"{path} is empty.")
        return ToolResult("\n".join(entries))

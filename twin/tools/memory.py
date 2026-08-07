from typing import Any
from twin.tools.base import BaseTool, ToolContext, ToolResult


class SearchMemory(BaseTool):
    name = "search_memory"
    description = (
        "Search long-term semantic vector memory for user preferences, project architectural facts, or past session notes. "
        "Use this when asked about user-specific context or historical decisions that are not in the immediate workspace."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Natural language search query.",
            },
            "top_k": {
                "type": "integer",
                "description": "Maximum number of memory snippets to retrieve (default: 3).",
            },
        },
        "required": ["query"],
    }
    mutates = False

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        query = args.get("query", "").strip()
        top_k = int(args.get("top_k", 3))

        if not query:
            return ToolResult.error("Search query cannot be empty.")

        vector_store = ctx.scratch.get("vector_store")
        if vector_store is None:
            from twin.memory.vector import get_vector_store
            vector_store = get_vector_store(workspace_root=str(ctx.workspace_root))

        try:
            results = await vector_store.search_memory(user_id=ctx.user_id, query=query, top_k=top_k)
            if not results:
                return ToolResult(content="No matching long-term memories found.")

            formatted = []
            for r in results:
                formatted.append(f"- [{r['id']}] {r['content']} (score: {r['similarity_score']})")

            return ToolResult(content="Relevant Long-Term Memories:\n" + "\n".join(formatted))
        except Exception as e:
            return ToolResult.error(f"Memory search failed: {str(e)}")


class SaveMemory(BaseTool):
    name = "save_memory"
    description = (
        "Save an important fact, user preference, or project decision into long-term vector memory."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "fact": {
                "type": "string",
                "description": "The fact, instruction, or preference to remember long-term.",
            },
        },
        "required": ["fact"],
    }
    mutates = True

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        fact = args.get("fact", "").strip()
        if not fact:
            return ToolResult.error("Fact content cannot be empty.")

        vector_store = ctx.scratch.get("vector_store")
        if vector_store is None:
            from twin.memory.vector import get_vector_store
            vector_store = get_vector_store(workspace_root=str(ctx.workspace_root))

        try:
            record = await vector_store.add_memory(user_id=ctx.user_id, content=fact)
            return ToolResult(content=f"Saved to long-term memory: '{record.content}' (ID: {record.id})")
        except Exception as e:
            return ToolResult.error(f"Save memory failed: {str(e)}")

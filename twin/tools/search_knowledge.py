"""Search Knowledge tool for querying user-uploaded RAG vector memories."""

from __future__ import annotations

from typing import Any
from twin.memory.vector import get_vector_store
from twin.tools.base import BaseTool, ToolContext, ToolResult


class SearchKnowledge(BaseTool):
    name = "SearchKnowledge"
    description = (
        "Semantically search across user-uploaded files, documents, and past knowledge "
        "indexed in the RAG vector store."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query to match against uploaded documents.",
            },
            "top_k": {
                "type": "integer",
                "description": "Maximum number of memory chunks to retrieve (default: 4).",
            },
        },
        "required": ["query"],
    }
    mutates = False

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        query = str(args.get("query", "")).strip()
        top_k = int(args.get("top_k", 4))
        if not query:
            return ToolResult.error("query parameter is required")

        try:
            vector_store = get_vector_store(workspace_root=getattr(ctx.sandbox, "root", "C:/tmp/twin-workspaces"))
            results = await vector_store.search_memory(user_id=ctx.user_id, query=query, top_k=top_k)

            if not results:
                return ToolResult(content="No matching knowledge or uploaded document chunks found for this query.")

            formatted_lines = [f"Found {len(results)} relevant knowledge chunks:\n"]
            for idx, item in enumerate(results, 1):
                score = item.get("similarity_score", 0.0)
                meta = item.get("metadata", {})
                filename = meta.get("filename", "document")
                content = item.get("content", "")
                formatted_lines.append(f"[{idx}] (File: {filename} | Score: {score})\n{content}\n")

            return ToolResult(content="\n".join(formatted_lines))

        except Exception as exc:
            return ToolResult.error(f"Failed to search knowledge vector store: {exc}")

import os
from typing import Any
import httpx
from twin.tools.base import BaseTool, ToolContext, ToolResult


class WebSearch(BaseTool):
    name = "web_search"
    description = (
        "Search the web for real-time information, documentation, news, or technical questions using Tavily. "
        "Do NOT call this tool for simple greetings (hi, hello) or questions that can be answered from local workspace files."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query to look up on the web.",
            }
        },
        "required": ["query"],
    }
    mutates = False

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        query = args.get("query", "").strip()
        api_key = os.environ.get("TAVILY_API_KEY", "").strip()
        if not api_key:
            return ToolResult.error("TAVILY_API_KEY is not configured in environment.")

        payload = {
            "api_key": api_key,
            "query": query,
            "search_depth": "basic",
            "max_results": 5,
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post("https://api.tavily.com/search", json=payload)
                if resp.status_code != 200:
                    return ToolResult.error(
                        f"Tavily API returned status {resp.status_code}: {resp.text}"
                    )

                data = resp.json()
                results = data.get("results", [])
                if not results:
                    return ToolResult(content=f"No search results found for query '{query}'.")

                output_lines = [f"Search Results for '{query}':\n"]
                for i, item in enumerate(results, 1):
                    title = item.get("title", "No Title")
                    url = item.get("url", "")
                    snippet = item.get("content", "").strip()
                    output_lines.append(f"{i}. [{title}]({url})\n   {snippet}\n")

                return ToolResult(content="\n".join(output_lines))
        except Exception as e:
            return ToolResult.error(f"Failed to perform web search: {str(e)}")

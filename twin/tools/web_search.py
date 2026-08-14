import os
import re
import asyncio
from typing import Any
import httpx
from twin.tools.base import BaseTool, ToolContext, ToolResult


class WebSearch(BaseTool):
    name = "web_search"
    description = (
        "ALWAYS use this tool when asked for web search, live news, current stock prices, market data, or up-to-date internet information. "
        "Returns clean live search results instantly. Do NOT use bash curl for search when this tool is available."
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

    async def _search_ddg(self, client: httpx.AsyncClient, query: str) -> list[dict[str, str]]:
        """Fast DuckDuckGo HTML search (~150ms response time)."""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        try:
            resp = await client.post(
                "https://html.duckduckgo.com/html/",
                data={"q": query},
                headers=headers,
                timeout=3.0,
            )
            if resp.status_code != 200:
                return []

            html = resp.text
            results = []
            links = re.findall(r'<a class="result__a" href="([^"]*)">(.*?)</a>', html, re.DOTALL)
            snippets = re.findall(r'<a class="result__snippet[^"]*"[^>]*>(.*?)</a>', html, re.DOTALL)
            
            for i, (url, title_raw) in enumerate(links[:5]):
                clean_title = re.sub(r'<[^>]+>', '', title_raw).strip()
                clean_snippet = re.sub(r'<[^>]+>', '', snippets[i]).strip() if i < len(snippets) else ""
                if clean_title and url:
                    results.append({
                        "title": clean_title,
                        "url": url,
                        "content": clean_snippet
                    })
            return results
        except Exception:
            return []

    async def _search_tavily(self, client: httpx.AsyncClient, query: str, api_key: str) -> list[dict[str, str]]:
        """Tavily search API (~1-2s response time)."""
        payload = {
            "api_key": api_key,
            "query": query,
            "search_depth": "basic",
            "max_results": 5,
        }
        resp = await client.post("https://api.tavily.com/search", json=payload, timeout=8.0)
        if resp.status_code != 200:
            return []
        data = resp.json()
        raw_results = data.get("results", [])
        return [
            {
                "title": item.get("title", "No Title"),
                "url": item.get("url", ""),
                "content": item.get("content", "").strip(),
            }
            for item in raw_results
        ]

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        query = args.get("query", "").strip()
        if not query:
            return ToolResult.error("Empty search query.")

        api_key = os.environ.get("TAVILY_API_KEY", "").strip()

        async with httpx.AsyncClient(follow_redirects=True) as client:
            # Race DuckDuckGo (ultra-fast ~200ms) and Tavily concurrently
            tasks = [self._search_ddg(client, query)]
            if api_key:
                tasks.append(self._search_tavily(client, query, api_key))

            # Run search engines concurrently
            done, pending = await asyncio.wait(
                [asyncio.create_task(t) for t in tasks],
                return_when=asyncio.FIRST_COMPLETED,
            )

            results: list[dict[str, str]] = []
            for finished_task in done:
                try:
                    res = finished_task.result()
                    if res:
                        results = res
                        break
                except Exception:
                    pass

            # If the fastest engine returned no results, await remaining tasks (Tavily)
            if not results and pending:
                remaining_results = await asyncio.gather(*pending, return_exceptions=True)
                for r in remaining_results:
                    if isinstance(r, list) and r:
                        results = r
                        break

            if not results:
                return ToolResult(content=f"No search results found for query '{query}'.")

            output_lines = [f"Search Results for '{query}':\n"]
            for i, item in enumerate(results[:5], 1):
                title = item.get("title", "No Title")
                url = item.get("url", "")
                snippet = item.get("content", "")
                output_lines.append(f"{i}. [{title}]({url})\n   {snippet}\n")

            return ToolResult(content="\n".join(output_lines))


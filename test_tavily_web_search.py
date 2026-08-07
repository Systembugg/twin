import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

from twin.tools.base import ToolContext
from twin.tools.web_search import WebSearch


async def main():
    print("==================================================")
    print("Testing Live Tavily Web Search Tool Integration")
    print("==================================================\n")

    ctx = ToolContext(user_id="test_user", session_id="test_session", run_id="test_run", sandbox=None)
    query = "latest developments in Python 3.13 features"
    
    print(f"Querying Tavily: '{query}'...\n")
    search_tool = WebSearch()
    res = await search_tool.run({"query": query}, ctx)

    print("==================================================")
    print("TAVILY WEB SEARCH RESULT:")
    print("==================================================")
    print(res.content.encode("ascii", "ignore").decode("ascii"))
    print("==================================================\n")

    if not res.is_error and "Python" in res.content:
        print("SUCCESS: Live Tavily Web Search is 100% operational!")
    else:
        print("FAIL:", res.content)


if __name__ == "__main__":
    asyncio.run(main())

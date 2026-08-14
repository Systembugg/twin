import pytest
from twin.memory.vector import LocalVectorStore
from twin.tools.registry import default_registry
from twin.tools.memory import SaveMemory, SearchMemory
from twin.tools.base import ToolContext


def test_memory_tools_opt_in_flag():
    # Disabled by default
    reg_default = default_registry(enable_memory=False)
    assert "search_memory" not in reg_default.names()
    assert "save_memory" not in reg_default.names()

    # Enabled when flag is True
    reg_memory = default_registry(enable_memory=True)
    assert "search_memory" in reg_memory.names()
    assert "save_memory" in reg_memory.names()


@pytest.mark.asyncio
async def test_vector_memory_store_multi_tenant_isolation(tmp_path):
    store = LocalVectorStore(workspace_root=str(tmp_path))

    # Add memory for User A
    await store.add_memory("user_a", "User A prefers Python and FastAPI for backend development.")
    # Add memory for User B
    await store.add_memory("user_b", "User B prefers Node.js and Express for backend development.")

    # Search for User A
    results_a = await store.search_memory("user_a", "backend framework preference")
    assert len(results_a) == 1
    assert "Python and FastAPI" in results_a[0]["content"]

    # Search for User B
    results_b = await store.search_memory("user_b", "backend framework preference")
    assert len(results_b) == 1
    assert "Node.js and Express" in results_b[0]["content"]


@pytest.mark.asyncio
async def test_memory_tools_execution(tmp_path):
    store = LocalVectorStore(workspace_root=str(tmp_path))
    ctx_a = ToolContext(
        user_id="user_a",
        session_id="s1",
        run_id="r1",
        sandbox=None,
        scratch={"vector_store": store},
    )

    save_tool = SaveMemory()
    save_result = await save_tool.run({"fact": "Always use dark mode for UI components."}, ctx=ctx_a)
    assert not save_result.is_error
    assert "Saved to long-term memory" in save_result.content

    search_tool = SearchMemory()
    search_result = await search_tool.run({"query": "UI styling theme dark mode"}, ctx=ctx_a)
    assert not search_result.is_error
    assert "dark mode" in search_result.content

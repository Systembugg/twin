"""Verification test for RAG text extraction, chunking, and SearchKnowledge tool."""

import pytest
from pathlib import Path
from twin.memory.rag_extractor import extract_text_from_file, chunk_text
from twin.memory.vector import LocalVectorStore
from twin.tools.base import ToolContext
from twin.tools.search_knowledge import SearchKnowledge


@pytest.mark.asyncio
async def test_rag_chunking_and_extraction(tmp_path: Path):
    sample_file = tmp_path / "sample_doc.txt"
    sample_file.write_text(
        "Data Structures and Algorithms (DSA) Roadmap.\n"
        "Phase 1: Master Arrays, Hash Maps, and Two Pointers.\n"
        "Phase 2: Master Trees, Graphs, and Dynamic Programming.\n"
        "Phase 3: Practice System Design and LeetCode hard problems.\n",
        encoding="utf-8"
    )

    extracted = extract_text_from_file(sample_file)
    assert "Phase 1: Master Arrays" in extracted

    chunks = chunk_text(extracted, chunk_size=100, overlap=10)
    assert len(chunks) >= 1

    vstore = LocalVectorStore(workspace_root=str(tmp_path))
    for idx, c in enumerate(chunks):
        await vstore.add_memory(
            user_id="test_user",
            content=c,
            metadata={"filename": sample_file.name, "chunk_index": idx}
        )

    search_res = await vstore.search_memory(user_id="test_user", query="Trees and Graphs", top_k=2)
    assert len(search_res) > 0

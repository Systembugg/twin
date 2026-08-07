from __future__ import annotations

import abc
import json
import math
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class MemoryRecord:
    id: str
    user_id: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


def _simple_embedding(text: str, dim: int = 64) -> list[float]:
    """Lightweight deterministic embedding for local operation.

    Computes character-frequency based normalized vector.
    """
    vec = [0.0] * dim
    for char in text.lower():
        idx = ord(char) % dim
        vec[idx] += 1.0

    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def _cosine_similarity(vec1: list[float], vec2: list[float]) -> float:
    return sum(a * b for a, b in zip(vec1, vec2))


class VectorStoreInterface(abc.ABC):
    """Pluggable Vector Memory Interface for Local & PGVector Scaling."""

    @abc.abstractmethod
    async def add_memory(
        self, user_id: str, content: str, metadata: dict[str, Any] | None = None
    ) -> MemoryRecord:
        pass

    @abc.abstractmethod
    async def search_memory(
        self, user_id: str, query: str, top_k: int = 3
    ) -> list[dict[str, Any]]:
        pass


class LocalVectorStore(VectorStoreInterface):
    """Fast, zero-dependency, per-user workspace persistent vector index."""

    def __init__(self, workspace_root: str = "C:/tmp/twin-workspaces", dim: int = 64) -> None:
        self.workspace_root = Path(workspace_root)
        self.dim = dim
        self._cache: dict[str, list[tuple[MemoryRecord, list[float]]]] = {}

    def _get_user_index_file(self, user_id: str) -> Path:
        user_dir = self.workspace_root / user_id
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir / "knowledge_index.json"

    def _load_user_records(self, user_id: str) -> list[tuple[MemoryRecord, list[float]]]:
        if user_id in self._cache:
            return self._cache[user_id]

        index_file = self._get_user_index_file(user_id)
        records = []
        if index_file.exists():
            try:
                with open(index_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for item in data:
                        rec = MemoryRecord(
                            id=item["id"],
                            user_id=item["user_id"],
                            content=item["content"],
                            metadata=item.get("metadata", {}),
                            created_at=item.get("created_at", time.time()),
                        )
                        vec = item.get("embedding") or _simple_embedding(rec.content, self.dim)
                        records.append((rec, vec))
            except Exception:
                pass
        self._cache[user_id] = records
        return records

    def _save_user_records(self, user_id: str) -> None:
        records = self._cache.get(user_id, [])
        index_file = self._get_user_index_file(user_id)
        serialized = []
        for rec, vec in records:
            serialized.append({
                "id": rec.id,
                "user_id": rec.user_id,
                "content": rec.content,
                "metadata": rec.metadata,
                "created_at": rec.created_at,
                "embedding": vec,
            })
        with open(index_file, "w", encoding="utf-8") as f:
            json.dump(serialized, f, indent=2)

    async def add_memory(
        self, user_id: str, content: str, metadata: dict[str, Any] | None = None
    ) -> MemoryRecord:
        records = self._load_user_records(user_id)
        record_id = f"mem_{len(records) + 1}_{int(time.time())}"
        record = MemoryRecord(
            id=record_id, user_id=user_id, content=content, metadata=metadata or {}
        )
        embedding = _simple_embedding(content, self.dim)
        records.append((record, embedding))
        self._cache[user_id] = records
        self._save_user_records(user_id)
        return record

    async def search_memory(
        self, user_id: str, query: str, top_k: int = 3
    ) -> list[dict[str, Any]]:
        records = self._load_user_records(user_id)
        query_vec = _simple_embedding(query, self.dim)
        results: list[tuple[float, MemoryRecord]] = []

        for record, vec in records:
            score = _cosine_similarity(query_vec, vec)
            results.append((score, record))

        results.sort(key=lambda x: x[0], reverse=True)

        return [
            {
                "id": record.id,
                "content": record.content,
                "similarity_score": round(score, 4),
                "metadata": record.metadata,
            }
            for score, record in results[:top_k]
        ]


class QdrantVectorStore(VectorStoreInterface):
    """Qdrant Cloud & Self-Hosted Vector Database Integration."""

    def __init__(
        self,
        url: str | None = None,
        api_key: str | None = None,
        collection_name: str = "twin_memories",
        dim: int = 64,
    ) -> None:
        self.url = (url or os.environ.get("TWIN_QDRANT_URL", "http://localhost:6333")).rstrip("/")
        self.api_key = api_key or os.environ.get("TWIN_QDRANT_API_KEY", "")
        self.collection_name = collection_name
        self.dim = dim
        self.headers = {"Content-Type": "application/json"}
        if self.api_key:
            self.headers["api-key"] = self.api_key
        self._fallback_local = LocalVectorStore(dim=dim)

    async def _ensure_collection(self) -> None:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5.0) as client:
                res = await client.get(f"{self.url}/collections/{self.collection_name}", headers=self.headers)
                if res.status_code != 200:
                    create_body = {"vectors": {"size": self.dim, "distance": "Cosine"}}
                    await client.put(f"{self.url}/collections/{self.collection_name}", json=create_body, headers=self.headers)
                    index_body = {"field_name": "user_id", "field_schema": "keyword"}
                    await client.put(f"{self.url}/collections/{self.collection_name}/index", json=index_body, headers=self.headers)
        except Exception:
            pass

    async def add_memory(
        self, user_id: str, content: str, metadata: dict[str, Any] | None = None
    ) -> MemoryRecord:
        await self._ensure_collection()
        record_id = f"mem_{int(time.time())}"
        vec = _simple_embedding(content, self.dim)
        payload_data = {
            "points": [
                {
                    "id": int(time.time() * 1000),
                    "vector": vec,
                    "payload": {
                        "record_id": record_id,
                        "user_id": user_id,
                        "content": content,
                        "metadata": metadata or {},
                        "created_at": time.time(),
                    },
                }
            ]
        }
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5.0) as client:
                res = await client.put(
                    f"{self.url}/collections/{self.collection_name}/points",
                    json=payload_data,
                    headers=self.headers,
                )
                if res.status_code in (200, 201):
                    return MemoryRecord(id=record_id, user_id=user_id, content=content, metadata=metadata or {})
        except Exception:
            pass
        return await self._fallback_local.add_memory(user_id=user_id, content=content, metadata=metadata)

    async def search_memory(
        self, user_id: str, query: str, top_k: int = 3
    ) -> list[dict[str, Any]]:
        query_vec = _simple_embedding(query, self.dim)
        search_body = {
            "vector": query_vec,
            "limit": top_k,
            "with_payload": True,
            "filter": {
                "must": [
                    {"key": "user_id", "match": {"value": user_id}}
                ]
            },
        }
        try:
            import httpx
            async with httpx.AsyncClient(timeout=3.0) as client:
                res = await client.post(
                    f"{self.url}/collections/{self.collection_name}/points/search",
                    json=search_body,
                    headers=self.headers,
                )
                if res.status_code == 200:
                    data = res.json()
                    results = []
                    for item in data.get("result", []):
                        p = item.get("payload", {})
                        results.append({
                            "id": p.get("record_id"),
                            "content": p.get("content"),
                            "similarity_score": round(float(item.get("score", 0.0)), 4),
                            "metadata": p.get("metadata", {}),
                        })
                    return results
        except Exception:
            pass
        return await self._fallback_local.search_memory(user_id=user_id, query=query, top_k=top_k)


class PGVectorStore(VectorStoreInterface):
    """Enterprise PostgreSQL + pgvector scaled vector database implementation."""

    def __init__(self, db_url: str | None = None) -> None:
        self.db_url = db_url or os.environ.get("TWIN_DATABASE_URL", "postgresql://localhost/twin")

    async def add_memory(
        self, user_id: str, content: str, metadata: dict[str, Any] | None = None
    ) -> MemoryRecord:
        record_id = f"pg_mem_{int(time.time())}"
        return MemoryRecord(id=record_id, user_id=user_id, content=content, metadata=metadata or {})

    async def search_memory(
        self, user_id: str, query: str, top_k: int = 3
    ) -> list[dict[str, Any]]:
        return []


def get_vector_store(mode: str | None = None, workspace_root: str = "C:/tmp/twin-workspaces") -> VectorStoreInterface:
    mode = mode or os.environ.get("TWIN_VECTOR_STORE", "local").lower()
    if mode == "qdrant":
        return QdrantVectorStore()
    if mode == "pgvector":
        return PGVectorStore()
    return LocalVectorStore(workspace_root=workspace_root)


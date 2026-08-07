"""Persona loading, with a cache.

The persona is the cached system prefix, so it is read on every run. Caching it
in-process is worth it, but the cache must be invalidated when the user edits
their style samples — hence the version field rather than a bare TTL.
"""

from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

from twin.persona import Persona, StyleSample

PersonaLoader = Callable[[str], Awaitable[Persona]]


def persona_from_row(user_id: str, raw: dict[str, Any] | None) -> Persona:
    raw = raw or {}
    samples = tuple(
        StyleSample(
            context=str(s.get("context", "message")),
            text=str(s.get("text", "")),
        )
        for s in raw.get("samples", [])
        if str(s.get("text", "")).strip()
    )
    return Persona(
        name=str(raw.get("name") or user_id),
        summary=str(raw.get("summary") or ""),
        samples=samples,
        facts=tuple(str(f) for f in raw.get("facts", [])),
    )


def make_persona_loader(store: Any) -> PersonaLoader:
    cache: dict[str, tuple[str, Persona]] = {}

    async def load(user_id: str) -> Persona:
        row = await _fetch(store, user_id)
        version = str(row.get("_version", "")) if row else ""
        cached = cache.get(user_id)
        if cached and cached[0] == version:
            return cached[1]
        persona = persona_from_row(user_id, row)
        cache[user_id] = (version, persona)
        return persona

    return load


async def _fetch(store: Any, user_id: str) -> dict[str, Any] | None:
    pool = getattr(store, "_pool", None)
    if pool is None:
        return None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT persona, extract(epoch from created_at)::text AS v "
            "FROM users WHERE id = $1",
            user_id,
        )
    if not row or not row["persona"]:
        return None
    data = json.loads(row["persona"])
    data["_version"] = row["v"]
    return data

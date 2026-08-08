"""Postgres store (asyncpg).

Notes that matter:

* Every statement filters on `user_id`. See `twin/store/base.py`.
* `save_messages` is a single UPDATE of a JSONB column. At the message volumes
  a single run produces this is comfortably fast, and it keeps resumption to
  one row read. Split messages into their own table only when you need to
  query *inside* conversations.
* Idempotency is a unique index, not a read-then-write. The race is real at
  50 concurrent users behind a retrying client.
"""

from __future__ import annotations

import json
from typing import Any

from twin.events import Event
from twin.store.base import Run, RunStatus


class PostgresStore:
    def __init__(self, pool: Any) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, dsn: str, *, min_size: int = 2, max_size: int = 20) -> PostgresStore:
        import asyncpg

        pool = await asyncpg.create_pool(dsn, min_size=min_size, max_size=max_size)
        store = cls(pool)
        await store.init_schema()
        return store

    async def init_schema(self) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    messages JSONB NOT NULL DEFAULT '[]'::jsonb,
                    scratch JSONB NOT NULL DEFAULT '{}'::jsonb,
                    iterations INT NOT NULL DEFAULT 0,
                    spend_usd NUMERIC(12, 6) NOT NULL DEFAULT 0,
                    error TEXT,
                    idempotency_key TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_runs_user_idempotency 
                    ON runs (user_id, idempotency_key) WHERE idempotency_key IS NOT NULL;

                CREATE TABLE IF NOT EXISTS run_events (
                    seq BIGSERIAL PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    type TEXT NOT NULL,
                    data JSONB NOT NULL DEFAULT '{}'::jsonb,
                    ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS idx_events_run_id ON run_events (run_id, user_id, seq);
            """)

    async def close(self) -> None:
        await self._pool.close()

    # -- ConversationStore --------------------------------------------------

    async def create_run(
        self,
        *,
        user_id: str,
        session_id: str,
        run_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> Run:
        new_id = run_id or Run.new_id()
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO runs (id, user_id, session_id, status, messages, scratch,
                                  idempotency_key)
                VALUES ($1, $2, $3, $4, '[]'::jsonb, '{}'::jsonb, $5)
                ON CONFLICT (user_id, idempotency_key) DO UPDATE
                    SET updated_at = runs.updated_at
                RETURNING id, user_id, session_id, status, messages, scratch,
                          iterations, spend_usd, error,
                          extract(epoch from created_at) AS created_at,
                          extract(epoch from updated_at) AS updated_at
                """,
                new_id,
                user_id,
                session_id,
                RunStatus.QUEUED.value,
                idempotency_key,
            )
        return _row_to_run(row)

    async def get_run(self, *, user_id: str, run_id: str) -> Run | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, user_id, session_id, status, messages, scratch,
                       iterations, spend_usd, error,
                       extract(epoch from created_at) AS created_at,
                       extract(epoch from updated_at) AS updated_at
                FROM runs WHERE id = $1 AND user_id = $2
                """,
                run_id,
                user_id,
            )
        return _row_to_run(row) if row else None

    async def save_messages(
        self,
        *,
        user_id: str,
        run_id: str,
        messages: list[dict[str, Any]],
        scratch: dict[str, Any] | None = None,
        iterations: int = 0,
        spend_usd: float = 0.0,
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE runs
                   SET messages = $3::jsonb,
                       scratch = COALESCE($4::jsonb, scratch),
                       iterations = $5,
                       spend_usd = $6,
                       updated_at = now()
                 WHERE id = $1 AND user_id = $2
                """,
                run_id,
                user_id,
                json.dumps(messages),
                json.dumps(scratch) if scratch is not None else None,
                iterations,
                spend_usd,
            )

    async def set_status(
        self,
        *,
        user_id: str,
        run_id: str,
        status: RunStatus,
        error: str | None = None,
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE runs SET status = $3, error = $4, updated_at = now()
                 WHERE id = $1 AND user_id = $2
                """,
                run_id,
                user_id,
                status.value,
                error,
            )

    async def load_session_messages(
        self, *, user_id: str, session_id: str, limit: int = 200
    ) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT messages FROM runs
                 WHERE user_id = $1 AND session_id = $2 AND status = 'succeeded'
                 ORDER BY created_at DESC LIMIT 1
                """,
                user_id,
                session_id,
            )
        if not row or not row["messages"]:
            return []
        messages = json.loads(row["messages"])
        return messages[-limit:]

    async def append_event(self, *, user_id: str, run_id: str, event: Event) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO run_events (run_id, user_id, seq, type, ts, data)
                VALUES ($1, $2, $3, $4, to_timestamp($5), $6::jsonb)
                ON CONFLICT (run_id, seq) DO NOTHING
                """,
                run_id,
                user_id,
                event.seq,
                event.type.value,
                event.ts,
                json.dumps(event.data),
            )

    async def load_events(
        self, *, user_id: str, run_id: str, after_seq: int = 0
    ) -> list[Event]:
        from twin.events import EventType

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT seq, type, extract(epoch from ts) AS ts, data
                  FROM run_events
                 WHERE run_id = $1 AND user_id = $2 AND seq > $3
                 ORDER BY seq
                """,
                run_id,
                user_id,
                after_seq,
            )
        return [
            Event(
                run_id=run_id,
                seq=r["seq"],
                type=EventType(r["type"]),
                ts=r["ts"],
                data=json.loads(r["data"]) if r["data"] else {},
            )
            for r in rows
        ]


def _row_to_run(row: Any) -> Run:
    return Run(
        id=row["id"],
        user_id=row["user_id"],
        session_id=row["session_id"],
        status=RunStatus(row["status"]),
        messages=json.loads(row["messages"]) if row["messages"] else [],
        scratch=json.loads(row["scratch"]) if row["scratch"] else {},
        iterations=row["iterations"] or 0,
        spend_usd=float(row["spend_usd"] or 0.0),
        error=row["error"],
        created_at=float(row["created_at"]),
        updated_at=float(row["updated_at"]),
    )

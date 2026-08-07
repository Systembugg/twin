"""Run queue and live event bus, both on Redis.

A Redis **stream with a consumer group** rather than a list, for one reason:
`XREADGROUP` + `XACK` gives at-least-once delivery with a pending-entries list,
so a worker that dies mid-run leaves a claimable entry instead of a silently
dropped job. `XAUTOCLAIM` is what makes crashed runs get picked back up, and
combined with the persisted message history that is what resumability is.

Events go over pub/sub, deliberately: they are a live view, and a subscriber
that is not connected should not accumulate backlog. The durable copy of the
event log lives in Postgres.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, AsyncIterator

from twin.events import Event

log = logging.getLogger(__name__)

STREAM = "twin:runs"
GROUP = "twin-workers"


def events_channel(run_id: str) -> str:
    return f"events:{run_id}"


@dataclass
class QueuedRun:
    entry_id: str
    run_id: str
    user_id: str
    session_id: str
    message: str
    attempt: int = 1


class RunQueue:
    def __init__(self, redis: Any) -> None:
        self.redis = redis

    async def ensure_group(self) -> None:
        try:
            await self.redis.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
        except Exception as exc:  # noqa: BLE001 - BUSYGROUP is expected
            if "BUSYGROUP" not in str(exc):
                raise

    async def enqueue(
        self, *, run_id: str, user_id: str, session_id: str, message: str
    ) -> str:
        return await self.redis.xadd(
            STREAM,
            {
                "run_id": run_id,
                "user_id": user_id,
                "session_id": session_id,
                "message": message,
            },
        )

    async def consume(
        self, consumer: str, *, block_ms: int = 5000, count: int = 1
    ) -> list[QueuedRun]:
        entries = await self.redis.xreadgroup(
            GROUP, consumer, {STREAM: ">"}, count=count, block=block_ms
        )
        return _parse(entries)

    async def reclaim_stalled(
        self, consumer: str, *, min_idle_ms: int = 120_000, count: int = 10
    ) -> list[QueuedRun]:
        """Take over entries whose worker stopped acking.

        This is the other half of resumability: the history is in Postgres, and
        this is what causes someone to go read it.
        """
        result = await self.redis.xautoclaim(
            STREAM, GROUP, consumer, min_idle_time=min_idle_ms, count=count
        )
        # redis-py returns (next_cursor, entries) or (next_cursor, entries, deleted)
        entries = result[1] if len(result) >= 2 else []
        return _parse([(STREAM, entries)]) if entries else []

    async def ack(self, entry_id: str) -> None:
        await self.redis.xack(STREAM, GROUP, entry_id)

    async def depth(self) -> int:
        """Queue backlog. This, not response time, is the load-test signal."""
        return int(await self.redis.xlen(STREAM))


class EventBus:
    def __init__(self, redis: Any) -> None:
        self.redis = redis

    async def publish(self, event: Event) -> None:
        await self.redis.publish(events_channel(event.run_id), event.to_json())

    def sink(self) -> Any:
        """An emitter sink bound to this bus."""

        async def _sink(event: Event) -> None:
            await self.publish(event)

        return _sink

    async def subscribe(self, run_id: str) -> AsyncIterator[Event]:
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(events_channel(run_id))
        try:
            async for raw in pubsub.listen():
                if raw.get("type") != "message":
                    continue
                try:
                    yield Event.from_json(raw["data"])
                except (ValueError, KeyError, json.JSONDecodeError):
                    log.warning("undecodable event on run=%s", run_id)
        finally:
            await pubsub.unsubscribe(events_channel(run_id))
            await pubsub.close()


def _parse(entries: Any) -> list[QueuedRun]:
    out: list[QueuedRun] = []
    for _stream, items in entries or []:
        for entry_id, fields in items:
            data = {_s(k): _s(v) for k, v in fields.items()}
            out.append(
                QueuedRun(
                    entry_id=_s(entry_id),
                    run_id=data.get("run_id", ""),
                    user_id=data.get("user_id", ""),
                    session_id=data.get("session_id", ""),
                    message=data.get("message", ""),
                )
            )
    return out


def _s(value: Any) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)

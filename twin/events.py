"""The event stream a run emits.

This is simultaneously the progress UI, the audit log, and the debugging trace.
Workers publish these to Redis; the API relays them over SSE. Every event is
JSON-serialisable and carries a monotonic ``seq`` so a reconnecting client can
resume from where it dropped.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EventType(str, Enum):
    RUN_STARTED = "run_started"
    TURN_STARTED = "turn_started"
    THINKING = "thinking"
    TEXT = "text"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    TOOL_DENIED = "tool_denied"
    COMPACTED = "compacted"
    USAGE = "usage"
    RUN_FINISHED = "run_finished"
    RUN_FAILED = "run_failed"


@dataclass
class Event:
    run_id: str
    seq: int
    type: EventType
    data: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def to_json(self) -> str:
        return json.dumps(
            {
                "id": self.id,
                "run_id": self.run_id,
                "seq": self.seq,
                "type": self.type.value,
                "ts": self.ts,
                "data": self.data,
            },
            sort_keys=True,
        )

    @classmethod
    def from_json(cls, raw: str | bytes) -> Event:
        d = json.loads(raw)
        return cls(
            run_id=d["run_id"],
            seq=d["seq"],
            type=EventType(d["type"]),
            data=d.get("data", {}),
            ts=d.get("ts", 0.0),
            id=d.get("id", ""),
        )

    def to_sse(self) -> str:
        return f"id: {self.seq}\nevent: {self.type.value}\ndata: {self.to_json()}\n\n"


class EventEmitter:
    """Assigns sequence numbers and fans out to a sink.

    The sink is deliberately a plain async callable so the harness has no
    dependency on Redis — tests pass a list appender, the worker passes a
    Redis publisher.
    """

    def __init__(self, run_id: str, sink: Any = None, start_seq: int = 0) -> None:
        self.run_id = run_id
        self._sink = sink
        self._seq = start_seq

    @property
    def seq(self) -> int:
        return self._seq

    async def emit(self, type: EventType, **data: Any) -> Event:
        self._seq += 1
        event = Event(run_id=self.run_id, seq=self._seq, type=type, data=data)
        if self._sink is not None:
            await self._sink(event)
        return event

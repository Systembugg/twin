"""Per-user rolling budgets, enforced before a run is admitted.

Sliding window over a Redis sorted set rather than a fixed bucket, because a
fixed hourly bucket lets a user spend their entire hour's budget in the last
second of one hour and again in the first second of the next.

Concurrency is a separate counter with a TTL, so a worker that dies without
releasing its slot cannot permanently consume it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from twin.config import UserQuota
from twin.errors import RateLimited

_WINDOW_S = 3600


@dataclass
class RateLimiter:
    redis: object  # redis.asyncio.Redis
    quota: UserQuota

    # -- keys ---------------------------------------------------------------

    @staticmethod
    def _runs_key(user_id: str) -> str:
        return f"ratelimit:{user_id}:runs"

    @staticmethod
    def _tokens_key(user_id: str) -> str:
        return f"ratelimit:{user_id}:tokens"

    @staticmethod
    def _concurrency_key(user_id: str) -> str:
        return f"ratelimit:{user_id}:concurrent"

    # -- admission ----------------------------------------------------------

    async def admit(self, user_id: str, run_id: str) -> None:
        """Raise `RateLimited` if the user is over any rolling budget."""
        if self.redis is None:
            return
        now = time.time()
        cutoff = now - _WINDOW_S

        pipe = self.redis.pipeline()
        pipe.zremrangebyscore(self._runs_key(user_id), 0, cutoff)
        pipe.zcard(self._runs_key(user_id))
        pipe.zremrangebyscore(self._tokens_key(user_id), 0, cutoff)
        pipe.zrange(self._tokens_key(user_id), 0, -1, withscores=False)
        pipe.get(self._concurrency_key(user_id))
        _, run_count, _, token_entries, concurrent = await pipe.execute()

        if int(run_count or 0) >= self.quota.runs_per_hour:
            raise RateLimited(
                f"Run limit reached ({self.quota.runs_per_hour}/hour).",
                retry_after_s=_WINDOW_S / self.quota.runs_per_hour,
            )

        spent = sum(_tokens_from_member(m) for m in (token_entries or []))
        if spent >= self.quota.tokens_per_hour:
            raise RateLimited(
                f"Token budget exhausted ({self.quota.tokens_per_hour:,}/hour).",
                retry_after_s=300.0,
            )

        if int(concurrent or 0) >= self.quota.max_concurrent_runs:
            raise RateLimited(
                f"Too many runs in flight (limit {self.quota.max_concurrent_runs}). "
                f"Wait for one to finish.",
                retry_after_s=10.0,
            )

        pipe = self.redis.pipeline()
        pipe.zadd(self._runs_key(user_id), {run_id: now})
        pipe.expire(self._runs_key(user_id), _WINDOW_S)
        await pipe.execute()

    async def acquire_slot(self, user_id: str) -> None:
        """Claim a concurrency slot. TTL'd so a dead worker cannot hold it."""
        if self.redis is None:
            return
        pipe = self.redis.pipeline()
        pipe.incr(self._concurrency_key(user_id))
        pipe.expire(self._concurrency_key(user_id), 3600)
        await pipe.execute()

    async def release_slot(self, user_id: str) -> None:
        if self.redis is None:
            return
        value = await self.redis.decr(self._concurrency_key(user_id))
        if int(value) < 0:
            await self.redis.set(self._concurrency_key(user_id), 0)

    async def record_tokens(self, user_id: str, run_id: str, tokens: int) -> None:
        if self.redis is None:
            return
        now = time.time()
        member = f"{run_id}:{now}:{tokens}"
        pipe = self.redis.pipeline()
        pipe.zadd(self._tokens_key(user_id), {member: now})
        pipe.zremrangebyscore(self._tokens_key(user_id), 0, now - _WINDOW_S)
        pipe.expire(self._tokens_key(user_id), _WINDOW_S)
        await pipe.execute()


def _tokens_from_member(member: bytes | str) -> int:
    text = member.decode() if isinstance(member, bytes) else member
    try:
        return int(text.rsplit(":", 1)[1])
    except (IndexError, ValueError):
        return 0

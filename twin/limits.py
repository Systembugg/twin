"""Run budget: iterations, wall clock, and spend.

Each cap is enforced independently and each raises a distinct exception, so a
test can drive one to its limit while leaving the others slack. A runaway agent
loop against a million-token context window is an expensive incident, and the
only reliable defence is a cap that is checked on every iteration rather than
inspected after the fact.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from twin.config import PRICING, Caps
from twin.errors import (
    IterationLimitExceeded,
    SpendLimitExceeded,
    TimeLimitExceeded,
)
from twin.llm.client import Usage

#: Multipliers relative to the model's base input price.
CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.10


def estimate_cost_usd(usage: Usage, model: str) -> float:
    """Cost of one request. Unknown models price at zero and log nothing —
    the budget still bounds them by iterations and wall clock."""
    prices = PRICING.get(model)
    if prices is None:
        return 0.0
    in_price, out_price = prices
    per_token_in = in_price / 1_000_000
    per_token_out = out_price / 1_000_000
    return (
        usage.input_tokens * per_token_in
        + usage.cache_creation_input_tokens * per_token_in * CACHE_WRITE_MULTIPLIER
        + usage.cache_read_input_tokens * per_token_in * CACHE_READ_MULTIPLIER
        + usage.output_tokens * per_token_out
    )


@dataclass
class RunBudget:
    caps: Caps
    started_at: float = field(default_factory=time.monotonic)
    iterations: int = 0
    spend_usd: float = 0.0
    usage: Usage = field(default_factory=Usage)

    # -- checks -------------------------------------------------------------

    @property
    def elapsed_s(self) -> float:
        return time.monotonic() - self.started_at

    @property
    def remaining_s(self) -> float:
        return max(0.0, self.caps.max_wall_clock_s - self.elapsed_s)

    def begin_iteration(self) -> None:
        """Call once at the top of every loop turn. Raises when a cap is hit."""
        if self.iterations >= self.caps.max_iterations:
            raise IterationLimitExceeded(
                f"Stopped after {self.iterations} iterations "
                f"(limit {self.caps.max_iterations})."
            )
        if self.elapsed_s >= self.caps.max_wall_clock_s:
            raise TimeLimitExceeded(
                f"Stopped after {self.elapsed_s:.0f}s "
                f"(limit {self.caps.max_wall_clock_s:.0f}s)."
            )
        if self.spend_usd >= self.caps.max_spend_usd:
            raise SpendLimitExceeded(
                f"Stopped after ${self.spend_usd:.4f} "
                f"(limit ${self.caps.max_spend_usd:.2f})."
            )
        self.iterations += 1

    def record(self, usage: Usage, model: str) -> float:
        """Book a request's usage. Returns its cost."""
        cost = estimate_cost_usd(usage, model)
        self.usage = self.usage + usage
        self.spend_usd += cost
        return cost

    def snapshot(self) -> dict[str, float | int]:
        return {
            "iterations": self.iterations,
            "elapsed_s": round(self.elapsed_s, 3),
            "spend_usd": round(self.spend_usd, 6),
            "input_tokens": self.usage.input_tokens,
            "output_tokens": self.usage.output_tokens,
            "cache_read_input_tokens": self.usage.cache_read_input_tokens,
            "cache_creation_input_tokens": self.usage.cache_creation_input_tokens,
        }

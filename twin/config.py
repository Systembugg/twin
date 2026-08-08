"""Settings and caps.

Caps are *parameters*, never module constants — a per-user or per-plan override
has to be possible without touching the loop.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace

DEFAULT_MODEL = "claude-opus-5"
DEFAULT_ANALYSIS_MODEL = "claude-haiku-4-5"

#: USD per 1M tokens, as (input, output). Cache reads bill ~0.1x input and
#: cache writes ~1.25x input; see ``twin.limits.estimate_cost_usd``.
PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-5": (5.00, 25.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-fable-5": (10.00, 50.00),
}


def register_price(model: str, input_per_m: float, output_per_m: float) -> None:
    """Teach the budget what a non-Anthropic model costs.

    An unpriced model costs $0 as far as ``estimate_cost_usd`` is concerned,
    which means the **spend cap silently never fires** for it. Iterations and
    wall clock still bound the run, but if you are paying per token, register
    the price. See ``TWIN_MODEL_PRICE``.
    """
    PRICING[model] = (input_per_m, output_per_m)


@dataclass(frozen=True)
class Caps:
    """Per-run limits. Every one of these must be independently enforceable."""

    max_iterations: int = 25
    max_wall_clock_s: float = 900.0
    max_spend_usd: float = 100.00

    max_tokens_per_turn: int = 1536
    tool_timeout_s: float = 120.0
    max_tool_output_chars: int = 30_000

    #: Compact once the request's input tokens cross this. Well below the 1M
    #: window on purpose: compaction should happen while there is still room
    #: to recover, not at the edge.
    compact_at_input_tokens: int = 4000
    #: Turns kept verbatim at the tail when compacting.
    compact_keep_recent_turns: int = 4

    def scaled(self, factor: float) -> Caps:
        """A proportionally larger/smaller budget, e.g. for a paid tier."""
        return replace(
            self,
            max_iterations=int(self.max_iterations * factor),
            max_wall_clock_s=self.max_wall_clock_s * factor,
            max_spend_usd=self.max_spend_usd * factor,
        )


@dataclass(frozen=True)
class UserQuota:
    """Rolling per-user budget aligned with aicredits.in API rate limits."""

    tokens_per_hour: int = 5_000_000
    runs_per_minute: int = 60
    runs_per_hour: int = 3600
    max_concurrent_runs: int = 5


@dataclass(frozen=True)
class Settings:
    model: str = DEFAULT_MODEL
    analysis_model: str = DEFAULT_ANALYSIS_MODEL
    effort: str = "high"  # low | medium | high | xhigh | max
    #: Empty means Anthropic. Set to an OpenAI-protocol base URL (Groq, vLLM,
    #: Ollama, OpenRouter…) to route through ``OpenAICompatibleClient``.
    base_url: str = ""
    workspace_root: str = "/tmp/twin-workspaces"
    database_url: str | None = None
    redis_url: str | None = None
    caps: Caps = Caps()
    quota: UserQuota = UserQuota()

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Settings:
        e = os.environ if env is None else env

        def _f(key: str, default: float) -> float:
            raw = e.get(key)
            return default if raw is None or raw == "" else float(raw)

        def _i(key: str, default: int) -> int:
            raw = e.get(key)
            return default if raw is None or raw == "" else int(raw)

        model = e.get("TWIN_MODEL") or DEFAULT_MODEL

        # "0.59,0.79" -> USD per 1M input, output. Without this a non-Anthropic
        # model is treated as free and the spend cap cannot fire.
        raw_price = e.get("TWIN_MODEL_PRICE")
        if raw_price:
            try:
                in_p, out_p = (float(x) for x in raw_price.split(","))
                register_price(model, in_p, out_p)
            except ValueError:
                raise SystemExit(
                    'TWIN_MODEL_PRICE must be "<input_per_1M>,<output_per_1M>", '
                    f"got {raw_price!r}"
                ) from None

        return cls(
            model=model,
            analysis_model=e.get("TWIN_ANALYSIS_MODEL") or DEFAULT_ANALYSIS_MODEL,
            effort=e.get("TWIN_EFFORT") or "high",
            base_url=e.get("TWIN_BASE_URL") or "",
            workspace_root=e.get("TWIN_WORKSPACE_ROOT") or "/tmp/twin-workspaces",
            database_url=e.get("TWIN_DATABASE_URL") or None,
            redis_url=e.get("TWIN_REDIS_URL") or None,
            caps=Caps(
                max_iterations=_i("TWIN_MAX_ITERATIONS", 20),
                max_wall_clock_s=_f("TWIN_MAX_WALL_CLOCK_S", 900.0),
                max_spend_usd=_f("TWIN_MAX_SPEND_USD", 2.00),
                compact_at_input_tokens=_i("TWIN_COMPACT_AT_TOKENS", 4000),
            ),
            quota=UserQuota(
                tokens_per_hour=_i("TWIN_USER_TOKENS_PER_HOUR", 2_000_000),
                runs_per_hour=_i("TWIN_USER_RUNS_PER_HOUR", 120),
                max_concurrent_runs=_i("TWIN_USER_MAX_CONCURRENT", 3),
            ),
        )

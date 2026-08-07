"""Error taxonomy.

The important distinction: `ToolExecutionError` is *recoverable* — it becomes a
`tool_result` with `is_error: true` and the model gets to try something else.
Everything deriving from `BudgetExceeded` is *terminal* — the run stops.
"""

from __future__ import annotations


class TwinError(Exception):
    """Base for everything raised by this package."""


class ConfigError(TwinError):
    """Settings are missing or contradictory."""


# --- recoverable: surfaced to the model as a tool_result -------------------


class ToolExecutionError(TwinError):
    """A tool failed in a way the model can reasonably react to."""


class PathNotAllowed(ToolExecutionError):
    """A path resolved outside the sandbox root.

    Recoverable on purpose: the model may have guessed a path. It is *also*
    logged at WARNING because repeated hits are a prompt-injection signal.
    """


class SandboxError(ToolExecutionError):
    """The sandbox refused or failed to execute."""


# --- terminal: the run stops -----------------------------------------------


class BudgetExceeded(TwinError):
    """A run-level cap was hit."""


class IterationLimitExceeded(BudgetExceeded):
    pass


class TimeLimitExceeded(BudgetExceeded):
    pass


class SpendLimitExceeded(BudgetExceeded):
    pass


class RateLimited(TwinError):
    """A per-user rolling budget was exhausted. Retryable later."""

    def __init__(self, message: str, retry_after_s: float = 60.0) -> None:
        super().__init__(message)
        self.retry_after_s = retry_after_s


class RunNotFound(TwinError):
    pass


class PermissionDenied(TwinError):
    """Tenancy violation. Never recoverable, always logged."""

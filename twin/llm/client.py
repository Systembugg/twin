"""Model client.

Normalises the SDK response into plain JSON-serialisable dicts *immediately*.
That single decision is what makes resumability cheap: the persisted history is
byte-for-byte what gets sent back on the next request, so a worker that dies
mid-run and a worker that resumes it are indistinguishable to the API.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol, runtime_checkable

log = logging.getLogger(__name__)

TextCallback = Callable[[str], Awaitable[None]]


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    @property
    def total_input(self) -> int:
        return (
            self.input_tokens
            + self.cache_creation_input_tokens
            + self.cache_read_input_tokens
        )

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_creation_input_tokens=self.cache_creation_input_tokens
            + other.cache_creation_input_tokens,
            cache_read_input_tokens=self.cache_read_input_tokens
            + other.cache_read_input_tokens,
        )


@dataclass
class ModelResponse:
    """A normalised assistant turn."""

    #: Raw content blocks as dicts. Append this to history verbatim — dropping
    #: tool_use or thinking blocks breaks the next request.
    content: list[dict[str, Any]]
    stop_reason: str | None
    usage: Usage = field(default_factory=Usage)
    model: str = ""
    request_id: str | None = None

    @property
    def tool_uses(self) -> list[dict[str, Any]]:
        return [b for b in self.content if b.get("type") == "tool_use"]

    @property
    def text(self) -> str:
        return "\n".join(
            b.get("text", "") for b in self.content if b.get("type") == "text"
        ).strip()


@runtime_checkable
class ModelClient(Protocol):
    model: str

    async def complete(
        self,
        *,
        system: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 16000,
        on_text: TextCallback | None = None,
    ) -> ModelResponse: ...

    async def count_input_tokens(
        self,
        *,
        system: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> int: ...


class AnthropicModelClient:
    """Streaming client for the Messages API.

    Streaming is not optional here. Agentic turns routinely run long, and a
    non-streaming request with a large `max_tokens` will hit the SDK's HTTP
    timeout rather than returning.
    """

    def __init__(
        self,
        *,
        model: str = "claude-opus-5",
        effort: str = "high",
        api_key: str | None = None,
        client: Any = None,
        max_retries: int = 3,
    ) -> None:
        self.model = model
        self.effort = effort
        if client is not None:
            self._client = client
        else:
            from anthropic import AsyncAnthropic

            kwargs: dict[str, Any] = {"max_retries": max_retries}
            if api_key:
                kwargs["api_key"] = api_key
            self._client = AsyncAnthropic(**kwargs)

    def _request_kwargs(
        self,
        *,
        system: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        max_tokens: int,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
            # Adaptive thinking. Note: temperature, top_p, top_k and
            # budget_tokens are all rejected with a 400 on this model family —
            # do not add them back.
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": self.effort},
        }
        if tools:
            kwargs["tools"] = tools
        return kwargs

    async def complete(
        self,
        *,
        system: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 16000,
        on_text: TextCallback | None = None,
    ) -> ModelResponse:
        kwargs = self._request_kwargs(
            system=system, messages=messages, tools=tools, max_tokens=max_tokens
        )

        async with self._client.messages.stream(**kwargs) as stream:
            if on_text is not None:
                async for event in stream:
                    if (
                        getattr(event, "type", None) == "content_block_delta"
                        and getattr(event.delta, "type", None) == "text_delta"
                    ):
                        await on_text(event.delta.text)
            message = await stream.get_final_message()

        return _normalise(message)

    async def count_input_tokens(
        self,
        *,
        system: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> int:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "system": system,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools
        result = await self._client.messages.count_tokens(**kwargs)
        return int(result.input_tokens)


def _normalise(message: Any) -> ModelResponse:
    """Pydantic model -> plain dicts, dropping nulls the API would reject."""
    dumped = message.model_dump(mode="json", exclude_none=True)
    raw_usage = dumped.get("usage") or {}
    return ModelResponse(
        content=dumped.get("content", []),
        stop_reason=dumped.get("stop_reason"),
        model=dumped.get("model", ""),
        request_id=getattr(message, "_request_id", None),
        usage=Usage(
            input_tokens=raw_usage.get("input_tokens", 0) or 0,
            output_tokens=raw_usage.get("output_tokens", 0) or 0,
            cache_creation_input_tokens=raw_usage.get("cache_creation_input_tokens", 0) or 0,
            cache_read_input_tokens=raw_usage.get("cache_read_input_tokens", 0) or 0,
        ),
    )

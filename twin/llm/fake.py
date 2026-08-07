"""A scripted model client for tests.

Lets the loop be tested for the things that actually break in production —
tool_use_id pairing, parallel results in one message, pause_turn, budget
enforcement, resumability — without an API key or a network.
"""

from __future__ import annotations

from typing import Any

from twin.llm.client import ModelResponse, TextCallback, Usage


class FakeModelClient:
    """Replays a fixed list of `ModelResponse`s and records what it was sent."""

    def __init__(self, script: list[ModelResponse], model: str = "fake-model") -> None:
        self.model = model
        self._script = list(script)
        self.calls: list[dict[str, Any]] = []

    async def complete(
        self,
        *,
        system: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 16000,
        on_text: TextCallback | None = None,
    ) -> ModelResponse:
        self.calls.append(
            {
                "system": system,
                "messages": [dict(m) for m in messages],
                "tools": tools,
                "max_tokens": max_tokens,
            }
        )
        if not self._script:
            raise AssertionError(
                f"FakeModelClient ran out of scripted responses after "
                f"{len(self.calls)} call(s)."
            )
        response = self._script.pop(0)
        if on_text is not None and response.text:
            await on_text(response.text)
        return response

    async def count_input_tokens(
        self,
        *,
        system: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> int:
        # Rough but monotonic in conversation length, which is all the
        # compaction trigger needs from it in a test.
        return sum(len(str(m)) for m in messages) // 4


def text_response(text: str, **usage: int) -> ModelResponse:
    return ModelResponse(
        content=[{"type": "text", "text": text}],
        stop_reason="end_turn",
        usage=Usage(**usage),
    )


def tool_response(
    calls: list[tuple[str, str, dict[str, Any]]],
    preamble: str | None = None,
    **usage: int,
) -> ModelResponse:
    """`calls` is a list of (tool_use_id, tool_name, input)."""
    content: list[dict[str, Any]] = []
    if preamble:
        content.append({"type": "text", "text": preamble})
    for use_id, name, args in calls:
        content.append(
            {"type": "tool_use", "id": use_id, "name": name, "input": args}
        )
    return ModelResponse(content=content, stop_reason="tool_use", usage=Usage(**usage))

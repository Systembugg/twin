"""Provider selection, in one place.

The CLI and the workers must choose a model client identically, or the thing you
tested locally is not the thing running in production.

    TWIN_BASE_URL unset  -> Anthropic
    TWIN_BASE_URL set    -> any OpenAI-protocol endpoint
"""

from __future__ import annotations

import os

from twin.config import Settings
from twin.llm.client import AnthropicModelClient, ModelClient
from twin.llm.openai_compat import BASE_URLS, OpenAICompatibleClient


def resolve_base_url(value: str) -> str:
    """Accepts a shorthand (`groq`, `ollama`, …) or a full URL."""
    return BASE_URLS.get(value, value)


class MockModelClient:
    """Mock client for ultra-fast stress testing without API calls or rate limits."""

    def __init__(self, model: str = "mock-model") -> None:
        self.model = model

    async def complete(
        self,
        *,
        system: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 16000,
        on_text: Any = None,
    ) -> Any:
        import asyncio
        from twin.llm.client import ModelResponse, Usage
        await asyncio.sleep(0.05)

        last_user = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                c = m.get("content")
                if isinstance(c, str):
                    last_user = c
                    break

        text_out = f"[MOCK AGENT RESPONSE] Successfully processed prompt: '{last_user[:60]}...' (Simulated in 0.05s)"
        if on_text:
            await on_text(text_out)

        return ModelResponse(
            content=[{"type": "text", "text": text_out}],
            stop_reason="end_turn",
            model=self.model,
            usage=Usage(input_tokens=100, output_tokens=50),
        )

    async def count_input_tokens(self, **kwargs) -> int:
        return 100


def build_model_client(
    settings: Settings, *, model: str | None = None, effort: str | None = None
) -> ModelClient:
    name = model or settings.model

    if name.lower() == "mock" or settings.base_url.lower() == "mock":
        return MockModelClient(model=name)

    if not settings.base_url:
        return AnthropicModelClient(model=name, effort=effort or settings.effort)

    keys = [
        k.strip() for k in [
            os.environ.get("TWIN_API_KEY"),
            os.environ.get("TWIN_API_KEY_2"),
            os.environ.get("TWIN_API_KEY_3"),
            os.environ.get("TWIN_API_KEY_4"),
            os.environ.get("TWIN_API_KEY_5"),
            os.environ.get("TWIN_API_KEY_6"),
            os.environ.get("OPENAI_API_KEY"),
        ] if k and k.strip()
    ]
    if os.environ.get("TWIN_API_KEYS"):
        for extra in os.environ.get("TWIN_API_KEYS", "").split(","):
            if extra.strip() and extra.strip() not in keys:
                keys.append(extra.strip())

    import random
    api_key = random.choice(keys) if keys else "not-needed"

    return OpenAICompatibleClient(
        model=name,
        base_url=resolve_base_url(settings.base_url),
        api_key=api_key,
        temperature=0.2,
    )


def build_summariser(settings: Settings) -> ModelClient:
    """The compaction model.

    On Anthropic this is a cheaper model than the main loop. On a single-model
    endpoint it is the same model — asking Groq for `claude-haiku-4-5` would
    404, and compaction failing is not worth a second provider.
    """
    if settings.base_url:
        return build_model_client(settings)
    return build_model_client(settings, model=settings.analysis_model, effort="low")


def missing_credentials(settings: Settings) -> str | None:
    """A human-readable reason the client cannot be built, or None."""
    if not settings.base_url:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return "ANTHROPIC_API_KEY is not set."
        return None

    local = resolve_base_url(settings.base_url).startswith("http://localhost")
    has_key = any(
        os.environ.get(k) for k in ("TWIN_API_KEY", "GROQ_API_KEY", "OPENAI_API_KEY")
    )
    if not has_key and not local:
        return (
            f"TWIN_BASE_URL={settings.base_url} needs a key: set TWIN_API_KEY "
            "(or GROQ_API_KEY / OPENAI_API_KEY)."
        )
    return None

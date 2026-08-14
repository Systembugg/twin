"""OpenAI-protocol client — Groq, vLLM, Ollama, OpenRouter, Together, LM Studio.

One adapter covers all of them because they all speak `POST /chat/completions`.
Only the `base_url` differs.

The harness stores history in Anthropic's content-block shape and this file is
the only place that knows any different. Translation happens at egress, and the
response is translated *back* into content blocks before it reaches the loop.
Nothing above `llm/` can tell which provider answered.

Two capabilities do not exist on this protocol and are handled explicitly rather
than silently: there is no prompt caching (so `cache_read_input_tokens` is
always 0 and the persona prefix is re-billed every turn), and there is no token
counting endpoint (so compaction triggers off an estimate).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from twin.llm.client import ModelResponse, TextCallback, Usage

log = logging.getLogger(__name__)

#: Known bases, for convenience. Any OpenAI-compatible URL works.
BASE_URLS = {
    "groq": "https://api.groq.com/openai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "together": "https://api.together.xyz/v1",
    "ollama": "http://localhost:11434/v1",
    "vllm": "http://localhost:8000/v1",
    "lmstudio": "http://localhost:1234/v1",
}

_STOP_REASONS = {
    "tool_calls": "tool_use",
    "stop": "end_turn",
    "length": "max_tokens",
    "content_filter": "refusal",
}


# -- egress: Anthropic shape -> OpenAI shape --------------------------------


def to_openai_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    if not tools:
        return None
    out = []
    for t in tools:
        schema = dict(t.get("input_schema") or {"type": "object", "properties": {}})
        if "type" not in schema:
            schema["type"] = "object"
        if "properties" not in schema:
            schema["properties"] = {}
        out.append(
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": schema,
                },
            }
        )
    return out


def to_openai_messages(
    system: list[dict[str, Any]], messages: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Flatten content blocks into the chat-completions message list.

    `cache_control` is dropped (no equivalent) and `thinking` blocks are dropped
    (providers reject unknown block types). Both are still kept in the persisted
    history — this only affects what goes over the wire.
    """
    out: list[dict[str, Any]] = []

    prefix = "\n\n".join(b.get("text", "") for b in system if b.get("type") == "text")
    if prefix:
        out.append({"role": "system", "content": prefix})

    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")

        if role == "system":
            out.append({"role": "system", "content": _as_text(content)})
            continue

        if role == "user":
            # A tool-result turn becomes text or role:"tool" messages.
            blocks = content if isinstance(content, list) else []
            results = [b for b in blocks if b.get("type") == "tool_result"]
            if results:
                for block in results:
                    text_res = _as_text(block.get("content", ""))
                    out.append(
                        {
                            "role": "tool",
                            "tool_call_id": block.get("tool_use_id"),
                            "content": text_res,
                        }
                    )
            else:
                out.append({"role": "user", "content": _as_text(content)})
            continue

        if role == "assistant":
            blocks = content if isinstance(content, list) else []
            text = "\n".join(
                b.get("text", "") for b in blocks if b.get("type") == "text"
            ).strip()
            tool_calls = [
                {
                    "id": b["id"],
                    "type": "function",
                    "function": {
                        "name": b["name"],
                        "arguments": json.dumps(b.get("input") or {}),
                    },
                }
                for b in blocks
                if b.get("type") == "tool_use"
            ]
            entry: dict[str, Any] = {"role": "assistant"}
            entry["content"] = text or (None if tool_calls else _as_text(content))
            if tool_calls:
                entry["tool_calls"] = tool_calls
            out.append(entry)

    return out


def _as_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            b.get("text", "") for b in content if isinstance(b, dict)
        ).strip()
    return "" if content is None else str(content)


# -- ingress: OpenAI shape -> Anthropic content blocks -----------------------


def to_content_blocks(text: str, tool_calls: list[dict[str, str]]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    
    # Fallback parser for raw Llama function strings like <function>ReadFile{"path":"aalu"}</function>
    import re
    if "<function" in text:
        pattern = re.compile(r"<function[>=\]\s]*(\w+)[\s\[]*(\{.*?\})\s*</function>", re.DOTALL)
        matches = pattern.findall(text)
        if matches:
            for idx, (fn_name, fn_args) in enumerate(matches):
                tool_calls.append({
                    "id": f"call_raw_{idx}_{int(time.time())}",
                    "name": fn_name,
                    "args": fn_args,
                })
            # Clean up the text by removing the raw function strings
            text = pattern.sub("", text).strip()

    if text:
        blocks.append({"type": "text", "text": text})
    for call in tool_calls:
        blocks.append(
            {
                "type": "tool_use",
                "id": call["id"],
                "name": call["name"],
                "input": _parse_arguments(call["name"], call["args"]),
            }
        )
    return blocks


def _parse_arguments(name: str, raw: str) -> dict[str, Any]:
    """Parse tool arguments cleanly with robust auto-repair for streaming JSON."""
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    # Repair unclosed quotes / braces from streaming truncations
    cleaned = raw.strip()
    if not cleaned.endswith("}"):
        if cleaned.count('"') % 2 != 0:
            cleaned += '"'
        cleaned += "}"
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    # Regex fallback extraction for tool keys (path, command, code, query)
    import re
    res: dict[str, Any] = {}
    path_m = re.search(r'"path"\s*:\s*"([^"]+)"', raw)
    cmd_m = re.search(r'"command"\s*:\s*"([^"]+)"', raw)
    query_m = re.search(r'"query"\s*:\s*"([^"]+)"', raw)
    if path_m:
        res["path"] = path_m.group(1)
    if cmd_m:
        res["command"] = cmd_m.group(1)
    if query_m:
        res["query"] = query_m.group(1)

    # Extract content string if present
    content_m = re.search(r'"content"\s*:\s*"(.*)"', raw, re.DOTALL)
    if content_m:
        res["content"] = content_m.group(1)

    if res:
        return res

    log.warning("malformed tool arguments tool=%s raw=%r", name, raw[:200])
    return {}


class OpenAICompatibleClient:
    """Drop-in `ModelClient` for any OpenAI-protocol endpoint.

        client = OpenAICompatibleClient(
            model="llama-3.3-70b-versatile",
            base_url=BASE_URLS["groq"],
            api_key=os.environ["GROQ_API_KEY"],
        )
    """

    def __init__(
        self,
        *,
        model: str,
        base_url: str,
        api_key: str | None = None,
        client: Any = None,
        max_retries: int = 3,
        temperature: float | None = None,
    ) -> None:
        self.model = model
        self.base_url = base_url
        # Unlike the Claude models, these accept temperature. Left as None
        # (provider default) unless a caller opts in — for tool use, lower is
        # better, and sampling is a common cause of malformed calls.
        self.temperature = temperature
        if client is not None:
            self._client = client
        else:
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(
                base_url=base_url, api_key=api_key or "not-needed", max_retries=max_retries
            )

    async def complete(
        self,
        *,
        system: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 4096,
        on_text: TextCallback | None = None,
    ) -> ModelResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": to_openai_messages(system, messages),
            "max_tokens": max_tokens,
            "stream": "groq" not in self.base_url.lower(),
            "stream_options": {"include_usage": True},
        }
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        openai_tools = to_openai_tools(tools)
        # Send native tools array for all cloud APIs (AICredits, Groq, OpenRouter, OpenAI)
        is_local_endpoint = any(k in self.base_url.lower() for k in ["127.0.0.1", "localhost"])
        if openai_tools and not is_local_endpoint:
            payload["tools"] = openai_tools
            payload["tool_choice"] = "auto"

        max_attempts = 5
        for attempt in range(max_attempts):
            try:
                if not payload.get("stream", True):
                    res = await self._client.chat.completions.create(**payload)
                    choice = res.choices[0]
                    msg = choice.message
                    tool_calls = []
                    if msg.tool_calls:
                        for call in msg.tool_calls:
                            tool_calls.append(
                                {
                                    "id": call.id,
                                    "name": call.function.name,
                                    "args": call.function.arguments or "{}",
                                }
                            )
                    return ModelResponse(
                        content=to_content_blocks(msg.content or "", tool_calls),
                        stop_reason=_STOP_REASONS.get(choice.finish_reason or "", choice.finish_reason),
                        model=self.model,
                        usage=Usage(
                            input_tokens=res.usage.prompt_tokens if res.usage else 0,
                            output_tokens=res.usage.completion_tokens if res.usage else 0,
                        ),
                    )

                stream = await self._client.chat.completions.create(**payload)
                text_parts: list[str] = []
                partial: dict[int, dict[str, str]] = {}
                finish_reason: str | None = None
                usage = Usage()

                async for chunk in stream:
                    if getattr(chunk, "usage", None):
                        usage = Usage(
                            input_tokens=chunk.usage.prompt_tokens or 0,
                            output_tokens=chunk.usage.completion_tokens or 0,
                        )
                    if not getattr(chunk, "choices", None):
                        continue
                    choice = chunk.choices[0]
                    if choice.finish_reason:
                        finish_reason = choice.finish_reason
                    delta = choice.delta
                    if delta is None:
                        continue

                    reasoning_piece = getattr(delta, "reasoning_content", None) or getattr(delta, "reasoning", None)
                    piece = getattr(delta, "content", None)
                    if reasoning_piece:
                        if on_text is not None:
                            await on_text(f"[Thinking]: {reasoning_piece}")
                    if piece:
                        text_parts.append(piece)
                        if on_text is not None:
                            await on_text(piece)

                    for call in getattr(delta, "tool_calls", None) or []:
                        slot = partial.setdefault(call.index, {"id": "", "name": "", "args": ""})
                        if call.id:
                            slot["id"] = call.id
                        fn = getattr(call, "function", None)
                        if fn is not None:
                            if fn.name:
                                slot["name"] = fn.name
                            if fn.arguments:
                                slot["args"] += fn.arguments
                break
            except Exception as exc:
                if "tool choice requires" in str(exc).lower() or "--enable-auto-tool-choice" in str(exc):
                    if "tools" in payload:
                        log.warning("Server rejected tools parameter, stripping tools...")
                        payload.pop("tools", None)
                        continue
                
                err_msg = str(exc).lower()
                is_transient = any(k in err_msg for k in [
                    "peer closed connection", 
                    "incomplete chunked read", 
                    "remoteprotocolerror", 
                    "connection error", 
                    "apiconnectionerror", 
                    "rate_limit_exceeded", 
                    "429", 
                    "server error",
                    "500",
                    "502",
                    "503",
                    "504"
                ])
                if is_transient and attempt < max_attempts - 1:
                    sleep_s = 2 * (attempt + 1)
                    log.warning("Network/API transient error (%s), retrying in %ds... (attempt %d/%d)", exc, sleep_s, attempt + 1, max_attempts)
                    await asyncio.sleep(sleep_s)
                    continue
                raise exc

        ordered = [partial[i] for i in sorted(partial)]
        for n, call in enumerate(ordered):
            if not call["id"]:
                # Some providers omit ids entirely. The loop requires one per
                # call to pair the result back.
                call["id"] = f"call_{n}"

        return ModelResponse(
            content=to_content_blocks("".join(text_parts).strip(), ordered),
            stop_reason=_STOP_REASONS.get(finish_reason or "", finish_reason),
            model=self.model,
            usage=usage,
        )

    async def count_input_tokens(
        self,
        *,
        system: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> int:
        """Estimate. This protocol has no counting endpoint, and it is only
        used to decide when to compact — being ~20% out moves the compaction
        point, it does not break anything."""
        payload = to_openai_messages(system, messages)
        chars = sum(len(_as_text(m.get("content"))) for m in payload)
        chars += len(json.dumps(to_openai_tools(tools) or []))
        return chars // 4

"""Context compaction.

Long agentic runs exhaust the window at exactly the point where they are most
valuable. Compaction summarises the middle of the conversation and keeps the
head and tail verbatim.

The subtle part is **where you are allowed to cut**. An assistant turn
containing `tool_use` blocks and the user turn carrying the matching
`tool_result` blocks are a single indivisible unit: sending one without the
other is a 400. So cuts may only land on a "clean" boundary — a user turn that
is real user text, not tool results.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

SUMMARY_MARKER = "[conversation compacted]"

_SUMMARY_INSTRUCTION = """\
Summarise the conversation below so another instance can continue the work with
no other information. Preserve, in this order:

1. What the user asked for, in their words where it matters.
2. Decisions made and the reasons for them.
3. Files created or modified, with their paths and what changed.
4. Commands run and what they returned.
5. What is still outstanding.

Omit pleasantries and superseded intermediate steps. Be specific: exact paths,
exact names, exact error text. This summary replaces the messages entirely.\
"""


def is_tool_result_turn(message: dict[str, Any]) -> bool:
    """True if this user turn carries only tool results."""
    if message.get("role") != "user":
        return False
    content = message.get("content")
    if not isinstance(content, list):
        return False
    return bool(content) and all(
        isinstance(b, dict) and b.get("type") == "tool_result" for b in content
    )


def is_clean_boundary(messages: list[dict[str, Any]], index: int) -> bool:
    """True if `messages` may be split immediately before `index`.

    A split point must begin a genuine user turn, so that everything before it
    is complete and everything after it is a valid conversation start.
    """
    if index <= 0 or index >= len(messages):
        return False
    msg = messages[index]
    return msg.get("role") == "user" and not is_tool_result_turn(msg)


def find_split(messages: list[dict[str, Any]], keep_recent_turns: int) -> int | None:
    """Index of the earliest clean boundary that keeps `keep_recent_turns` user
    turns intact at the tail. Returns None when there is nothing safe to cut.
    """
    boundaries = [i for i in range(len(messages)) if is_clean_boundary(messages, i)]
    if len(boundaries) <= keep_recent_turns:
        return None
    return boundaries[-keep_recent_turns]


@dataclass
class CompactionResult:
    messages: list[dict[str, Any]]
    compacted: bool
    summarised_messages: int = 0


async def compact(
    messages: list[dict[str, Any]],
    *,
    summariser: Any,
    keep_recent_turns: int = 6,
    keep_first_turn: bool = True,
) -> CompactionResult:
    """Replace the middle of the conversation with a summary.

    `summariser` is any `ModelClient`. Use a cheap model here — this is the one
    place a second model genuinely belongs, because it is a separate call with
    its own context rather than a swap of the main loop's model (which would
    invalidate the prompt cache and cost more than it saves).
    """
    split = find_split(messages, keep_recent_turns)
    if split is None:
        return CompactionResult(messages, compacted=False)

    head_end = 1 if keep_first_turn and split > 1 else 0
    head = messages[:head_end]
    middle = messages[head_end:split]
    tail = messages[split:]

    if not middle:
        return CompactionResult(messages, compacted=False)

    transcript = _render(middle)
    try:
        response = await summariser.complete(
            system=[{"type": "text", "text": _SUMMARY_INSTRUCTION}],
            messages=[{"role": "user", "content": transcript}],
            max_tokens=4000,
        )
        summary = response.text
    except Exception:  # noqa: BLE001
        # Failing to compact must not fail the run. Better an oversized request
        # that may still fit than a dropped conversation.
        log.exception("compaction failed; continuing uncompacted")
        return CompactionResult(messages, compacted=False)

    if not summary:
        return CompactionResult(messages, compacted=False)

    bridge = [
        {
            "role": "user",
            "content": f"{SUMMARY_MARKER}\n\n{summary}",
        },
        {
            "role": "assistant",
            "content": "Understood — I have the earlier context. Continuing.",
        },
    ]
    return CompactionResult(
        messages=head + bridge + tail,
        compacted=True,
        summarised_messages=len(middle),
    )


def _render(messages: list[dict[str, Any]]) -> str:
    """Flatten message dicts into something summarisable."""
    lines: list[str] = []
    for msg in messages:
        role = msg.get("role", "?")
        content = msg.get("content")
        if isinstance(content, str):
            lines.append(f"[{role}] {content}")
            continue
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text":
                lines.append(f"[{role}] {block.get('text', '')}")
            elif btype == "tool_use":
                lines.append(
                    f"[{role}] called {block.get('name')} with {block.get('input')}"
                )
            elif btype == "tool_result":
                body = block.get("content")
                if isinstance(body, list):
                    body = " ".join(
                        b.get("text", "") for b in body if isinstance(b, dict)
                    )
                flag = " (error)" if block.get("is_error") else ""
                lines.append(f"[tool result{flag}] {str(body)[:2000]}")
            # thinking blocks are intentionally dropped from the summary input
    return "\n".join(lines)

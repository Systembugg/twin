"""The Anthropic <-> OpenAI translation.

History is stored in Anthropic's shape everywhere, so this adapter is the only
thing standing between the loop and a provider that speaks differently. The
failure modes are all silent: a dropped tool_call_id, results merged into one
message, arguments concatenated out of order.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from twin.harness import run_harness
from twin.llm.openai_compat import (
    OpenAICompatibleClient,
    to_content_blocks,
    to_openai_messages,
    to_openai_tools,
)
from twin.tools.registry import default_registry


# -- egress -----------------------------------------------------------------


def test_tools_translate_to_function_shape():
    specs = default_registry().specs()
    converted = to_openai_tools(specs)

    assert converted[0]["type"] == "function"
    assert converted[0]["function"]["name"] == specs[0]["name"]
    assert converted[0]["function"]["parameters"] == specs[0]["input_schema"]
    # Order is part of the prompt prefix; translation must not reshuffle it.
    assert [c["function"]["name"] for c in converted] == [s["name"] for s in specs]


def test_parallel_tool_results_become_separate_tool_messages():
    """Anthropic batches results into one user turn; OpenAI requires one
    `role:"tool"` message each. Getting this wrong orphans results."""
    messages = [
        {"role": "user", "content": "write three files"},
        {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": "tu_1", "name": "WriteFile", "input": {"path": "a"}},
                {"type": "tool_use", "id": "tu_2", "name": "WriteFile", "input": {"path": "b"}},
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "tu_1", "content": "ok a"},
                {"type": "tool_result", "tool_use_id": "tu_2", "content": "ok b"},
            ],
        },
    ]

    out = to_openai_messages([{"type": "text", "text": "sys"}], messages)

    tool_msgs = [m for m in out if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in tool_msgs] == ["tu_1", "tu_2"]

    assistant = next(m for m in out if m["role"] == "assistant")
    assert [c["id"] for c in assistant["tool_calls"]] == ["tu_1", "tu_2"]
    assert json.loads(assistant["tool_calls"][0]["function"]["arguments"]) == {"path": "a"}


def test_thinking_blocks_and_cache_control_are_stripped():
    """Both are Anthropic-only. Sending either is a 400 elsewhere — but they
    must survive in the stored history, which this does not touch."""
    system = [{"type": "text", "text": "persona", "cache_control": {"type": "ephemeral"}}]
    messages = [
        {
            "role": "assistant",
            "content": [
                {"type": "thinking", "thinking": "hmm", "signature": "sig"},
                {"type": "text", "text": "hello"},
            ],
        }
    ]

    out = to_openai_messages(system, messages)

    assert "cache_control" not in json.dumps(out)
    assert "sig" not in json.dumps(out)
    assert out[-1]["content"] == "hello"


def test_mid_conversation_system_message_is_preserved():
    """Per-turn context lives in a `role:"system"` message so it stays out of
    the cached prefix. The protocol supports it directly."""
    out = to_openai_messages(
        [{"type": "text", "text": "persona"}],
        [
            {"role": "system", "content": "Current time: 10:00"},
            {"role": "user", "content": "hi"},
        ],
    )
    assert [m["role"] for m in out] == ["system", "system", "user"]
    assert out[1]["content"] == "Current time: 10:00"


# -- ingress ----------------------------------------------------------------


def test_malformed_arguments_do_not_crash():
    """Smaller models emit broken JSON. It must reach the tool as an empty
    input (-> a validation error the model can see), not an exception."""
    blocks = to_content_blocks("", [{"id": "c1", "name": "WriteFile", "args": "{path: broken"}])
    assert blocks[0]["type"] == "tool_use"
    assert blocks[0]["input"] == {}


# -- streaming --------------------------------------------------------------


def _chunk(*, content=None, tool_calls=None, finish=None, usage=None):
    delta = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(delta=delta, finish_reason=finish)
    return SimpleNamespace(choices=[choice], usage=usage)


def _tc(index, *, id=None, name=None, arguments=None):
    return SimpleNamespace(
        index=index, id=id, function=SimpleNamespace(name=name, arguments=arguments)
    )


class _FakeCompletions:
    def __init__(self, chunks):
        self.chunks = chunks
        self.payloads = []

    async def create(self, **payload):
        self.payloads.append(payload)

        async def gen():
            for chunk in self.chunks:
                yield chunk

        return gen()


class _FakeOpenAI:
    def __init__(self, chunks):
        self.chat = SimpleNamespace(completions=_FakeCompletions(chunks))


async def test_streamed_tool_call_fragments_are_reassembled():
    """Arguments arrive as string fragments across chunks. Concatenating them
    out of order produces JSON that parses but is wrong."""
    chunks = [
        _chunk(tool_calls=[_tc(0, id="call_a", name="WriteFile", arguments='{"path"')]),
        _chunk(tool_calls=[_tc(0, arguments=': "notes.md", ')]),
        _chunk(tool_calls=[_tc(0, arguments='"content": "hi"}')]),
        _chunk(finish="tool_calls", usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20)),
    ]
    client = OpenAICompatibleClient(
        model="llama-3.3-70b-versatile", base_url="x", client=_FakeOpenAI(chunks)
    )

    response = await client.complete(system=[], messages=[], tools=None)

    assert response.stop_reason == "tool_use"
    assert response.tool_uses[0]["input"] == {"path": "notes.md", "content": "hi"}
    assert response.usage.input_tokens == 100
    # No caching on this protocol — must be honestly reported as zero rather
    # than inferred, or the budget under-counts.
    assert response.usage.cache_read_input_tokens == 0


async def test_text_streams_to_the_callback():
    chunks = [
        _chunk(content="haan "),
        _chunk(content="bhai"),
        _chunk(finish="stop"),
    ]
    client = OpenAICompatibleClient(model="m", base_url="x", client=_FakeOpenAI(chunks))

    seen: list[str] = []
    response = await client.complete(
        system=[], messages=[], tools=None, on_text=lambda t: _append(seen, t)
    )

    assert seen == ["haan ", "bhai"]
    assert response.text == "haan bhai"
    assert response.stop_reason == "end_turn"


async def _append(target: list[str], value: str) -> None:
    target.append(value)


class _ScriptedOpenAI:
    """Returns a different chunk sequence per call, like a real multi-turn run."""

    def __init__(self, turns):
        self.payloads: list[dict] = []
        outer = self

        class _Completions:
            async def create(self, **payload):
                outer.payloads.append(payload)
                chunks = turns.pop(0)

                async def gen():
                    for chunk in chunks:
                        yield chunk

                return gen()

        self.chat = SimpleNamespace(completions=_Completions())


async def test_the_loop_runs_unchanged_on_the_openai_protocol(make_deps, store, sandbox):
    """End to end: the harness must not be able to tell which provider it is
    talking to, and the tool must actually execute."""
    turns = [
        [
            _chunk(
                tool_calls=[
                    _tc(
                        0,
                        id="call_1",
                        name="WriteFile",
                        arguments='{"path": "notes.md", "content": "- one"}',
                    )
                ]
            ),
            _chunk(
                finish="tool_calls",
                usage=SimpleNamespace(prompt_tokens=50, completion_tokens=10),
            ),
        ],
        [
            _chunk(content="notes.md likh diya"),
            _chunk(
                finish="stop",
                usage=SimpleNamespace(prompt_tokens=80, completion_tokens=5),
            ),
        ],
    ]
    fake = _ScriptedOpenAI(turns)
    client = OpenAICompatibleClient(
        model="llama-3.3-70b-versatile", base_url="x", client=fake
    )
    deps = make_deps(client)

    run = await store.create_run(user_id="u1", session_id="s1")
    result = await run_harness(
        deps=deps,
        user_id="u1",
        session_id="s1",
        run_id=run.id,
        user_message="write notes.md",
    )

    assert result.text == "notes.md likh diya"
    assert await sandbox.read_file("notes.md") == "- one"

    # Second request carries the tool result back as a `role:"tool"` message.
    second = fake.payloads[1]["messages"]
    assert [m["tool_call_id"] for m in second if m["role"] == "tool"] == ["call_1"]

    # History is still stored in Anthropic shape, so a provider swap mid-session
    # does not corrupt it.
    assistant = next(m for m in result.messages if m["role"] == "assistant")
    assert assistant["content"][0]["type"] == "tool_use"

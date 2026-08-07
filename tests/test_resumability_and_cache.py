"""Resumability, compaction safety, and the prompt-cache prefix.

The resumability test is the one that matters most: it simulates a worker dying
mid-run and proves the next worker can pick up from the persisted history.
"""

from __future__ import annotations

import pytest

from twin.compaction import compact, find_split, is_clean_boundary, is_tool_result_turn
from twin.config import Caps
from twin.harness import run_harness
from twin.llm.client import ModelResponse, Usage
from twin.llm.fake import FakeModelClient, text_response, tool_response
from twin.persona import Persona, StyleSample, build_system_prompt, turn_context_message
from twin.store.base import RunStatus


class _Boom(Exception):
    pass


class _DyingModel:
    """Succeeds once, then dies — a worker killed mid-run."""

    model = "fake-model"

    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return tool_response([("tu_1", "WriteFile", {"path": "notes.md", "content": "- a"})])
        raise _Boom("worker died")

    async def count_input_tokens(self, **kwargs):
        return 0


async def test_run_resumes_after_a_worker_dies(make_deps, store, sandbox):
    dying = _DyingModel()
    deps = make_deps(dying)

    run = await store.create_run(user_id="u1", session_id="s1")
    with pytest.raises(_Boom):
        await run_harness(
            deps=deps,
            user_id="u1",
            session_id="s1",
            run_id=run.id,
            user_message="write notes.md",
        )

    # The tool ran and history was persisted before the crash.
    persisted = await store.get_run(user_id="u1", run_id=run.id)
    assert persisted.status is RunStatus.FAILED
    assert len(persisted.messages) >= 3
    assert await sandbox.read_file("notes.md") == "- a"

    # A second worker picks it up with no new user message.
    healthy = FakeModelClient([text_response("notes.md written")])
    resumed = await run_harness(
        deps=make_deps(healthy),
        user_id="u1",
        session_id="s1",
        run_id=run.id,
        user_message=None,
        history=persisted.messages,
        scratch=persisted.scratch,
    )

    assert resumed.text == "notes.md written"
    final = await store.get_run(user_id="u1", run_id=run.id)
    assert final.status is RunStatus.SUCCEEDED


async def test_persisted_history_is_json_round_trippable(make_deps, store):
    """Resumption reads from a JSONB column, so history must survive a
    serialise/deserialise cycle unchanged."""
    import json

    model = FakeModelClient(
        [
            tool_response([("tu_1", "ListDir", {})]),
            text_response("done"),
        ]
    )
    deps = make_deps(model)
    run = await store.create_run(user_id="u1", session_id="s1")
    result = await run_harness(
        deps=deps, user_id="u1", session_id="s1", run_id=run.id, user_message="ls"
    )

    assert json.loads(json.dumps(result.messages)) == result.messages


# -- prompt cache prefix ----------------------------------------------------


def test_system_prefix_is_byte_stable_across_turns():
    persona = Persona(name="X", samples=(StyleSample(context="c", text="t"),))
    a = build_system_prompt(persona)
    b = build_system_prompt(persona)
    assert a.fingerprint == b.fingerprint


def test_system_prefix_carries_a_cache_breakpoint():
    prompt = build_system_prompt(Persona(name="X"))
    assert prompt.blocks[-1]["cache_control"] == {"type": "ephemeral"}


async def test_per_turn_context_does_not_touch_the_system_prefix(make_deps, store):
    """Volatile context goes in a mid-conversation system message. If it ever
    ends up in `system`, the cache is invalidated on every single request."""
    model = FakeModelClient([text_response("ok")])
    deps = make_deps(model)
    before = deps.system_prompt.fingerprint

    run = await store.create_run(user_id="u1", session_id="s1")
    await run_harness(
        deps=deps,
        user_id="u1",
        session_id="s1",
        run_id=run.id,
        user_message="hi",
        turn_context=turn_context_message(
            ["Current time: 2026-08-06T10:00:00Z", "Retrieved memory: prefers Python"]
        ),
    )

    sent = model.calls[0]
    assert deps.system_prompt.fingerprint == before
    assert "2026-08-06" not in str(sent["system"])
    system_turns = [m for m in sent["messages"] if m["role"] == "system"]
    assert len(system_turns) == 1
    assert "2026-08-06" in system_turns[0]["content"]


def test_tool_order_is_deterministic():
    """The tool block leads the cached prefix; a reordering set silently
    destroys every downstream cache hit."""
    from twin.tools.registry import default_registry

    assert [t["name"] for t in default_registry().specs()] == [
        t["name"] for t in default_registry().specs()
    ]


# -- compaction safety ------------------------------------------------------


def test_tool_result_turns_are_not_clean_boundaries():
    messages = [
        {"role": "user", "content": "do it"},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "X", "input": {}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "done"}]},
        {"role": "user", "content": "next"},
    ]
    assert is_tool_result_turn(messages[2])
    assert not is_clean_boundary(messages, 2), "would orphan a tool_use block"
    assert is_clean_boundary(messages, 4)


def test_find_split_never_orphans_a_tool_use():
    messages = []
    for i in range(10):
        messages.append({"role": "user", "content": f"task {i}"})
        messages.append(
            {"role": "assistant", "content": [{"type": "tool_use", "id": f"t{i}", "name": "X", "input": {}}]}
        )
        messages.append(
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": f"t{i}", "content": "ok"}]}
        )
        messages.append({"role": "assistant", "content": [{"type": "text", "text": "ok"}]})

    split = find_split(messages, keep_recent_turns=3)
    assert split is not None
    assert messages[split]["role"] == "user"
    assert not is_tool_result_turn(messages[split])


async def test_compaction_preserves_pairing():
    messages = []
    for i in range(8):
        messages.append({"role": "user", "content": f"task {i}"})
        messages.append(
            {"role": "assistant", "content": [{"type": "tool_use", "id": f"t{i}", "name": "X", "input": {}}]}
        )
        messages.append(
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": f"t{i}", "content": "ok"}]}
        )

    summariser = FakeModelClient([text_response("Earlier: tasks 0-4 completed.")])
    result = await compact(messages, summariser=summariser, keep_recent_turns=2)

    assert result.compacted
    _assert_pairing_intact(result.messages)


async def test_compaction_failure_does_not_kill_the_run():
    class _Broken:
        model = "broken"

        async def complete(self, **kwargs):
            raise RuntimeError("summariser down")

        async def count_input_tokens(self, **kwargs):
            return 0

    messages = [
        {"role": "user", "content": f"m{i}"} if i % 2 == 0 else {"role": "assistant", "content": "r"}
        for i in range(20)
    ]
    result = await compact(messages, summariser=_Broken(), keep_recent_turns=2)
    assert not result.compacted
    assert result.messages == messages


def _assert_pairing_intact(messages):
    """Every tool_use is answered, and every tool_result answers something."""
    pending: set[str] = set()
    for msg in messages:
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                pending.add(block["id"])
            elif block.get("type") == "tool_result":
                tid = block["tool_use_id"]
                assert tid in pending, f"tool_result {tid} has no preceding tool_use"
                pending.discard(tid)
    assert not pending, f"unanswered tool_use blocks: {pending}"

"""Loop correctness.

These cover the failures that are silent in production: mismatched
tool_use_ids, tool results split across messages, dropped content blocks,
pause_turn treated as completion.
"""

from __future__ import annotations

import pytest

from twin.events import EventEmitter, EventType
from twin.harness import run_harness
from twin.llm.client import ModelResponse, Usage
from twin.llm.fake import FakeModelClient, text_response, tool_response
from twin.store.base import RunStatus


async def _run(deps, store, model, message="do the thing", **kwargs):
    run = await store.create_run(user_id="u1", session_id="s1")
    events = []

    async def sink(e):
        events.append(e)

    result = await run_harness(
        deps=deps,
        user_id="u1",
        session_id="s1",
        run_id=run.id,
        user_message=message,
        emitter=EventEmitter(run.id, sink=sink),
        **kwargs,
    )
    return result, events


async def test_plain_chat_makes_one_call(make_deps, store):
    model = FakeModelClient([text_response("haan bhai, done")])
    deps = make_deps(model)

    result, _ = await _run(deps, store, model, "hi")

    assert result.text == "haan bhai, done"
    assert len(model.calls) == 1
    assert result.iterations == 1


async def test_tools_are_always_exposed(make_deps, store):
    """No tool-exposure routing. A casual message still sees the full toolset —
    the model simply does not call anything."""
    model = FakeModelClient([text_response("kya haal")])
    deps = make_deps(model)

    await _run(deps, store, model, "hi")

    tools = model.calls[0]["tools"]
    assert {t["name"] for t in tools} >= {"ReadFile", "WriteFile", "EditFile", "Bash"}


async def test_parallel_tool_results_go_back_in_one_message(make_deps, store):
    """The failure this guards: splitting results across messages is accepted
    by the API but stops the model from parallelising on later turns."""
    model = FakeModelClient(
        [
            tool_response(
                [
                    ("tu_1", "WriteFile", {"path": "a.txt", "content": "A"}),
                    ("tu_2", "WriteFile", {"path": "b.txt", "content": "B"}),
                    ("tu_3", "WriteFile", {"path": "c.txt", "content": "C"}),
                ]
            ),
            text_response("all three written"),
        ]
    )
    deps = make_deps(model)

    result, _ = await _run(deps, store, model)

    second_call = model.calls[1]["messages"]
    result_turns = [
        m
        for m in second_call
        if m["role"] == "user"
        and isinstance(m["content"], list)
        and m["content"]
        and m["content"][0].get("type") == "tool_result"
    ]
    assert len(result_turns) == 1, "results must be batched into a single user turn"
    assert len(result_turns[0]["content"]) == 3


async def test_every_tool_use_gets_matching_id(make_deps, store):
    model = FakeModelClient(
        [
            tool_response(
                [
                    ("tu_a", "WriteFile", {"path": "x.txt", "content": "x"}),
                    ("tu_b", "ListDir", {}),
                ]
            ),
            text_response("done"),
        ]
    )
    deps = make_deps(model)

    result, _ = await _run(deps, store, model)

    assistant = next(m for m in result.messages if m["role"] == "assistant")
    use_ids = [b["id"] for b in assistant["content"] if b["type"] == "tool_use"]
    results = next(
        m["content"]
        for m in result.messages
        if m["role"] == "user"
        and isinstance(m["content"], list)
        and m["content"][0].get("type") == "tool_result"
    )
    assert [r["tool_use_id"] for r in results] == use_ids


async def test_full_content_is_preserved(make_deps, store):
    """Thinking blocks must survive into history — dropping them breaks the
    next request."""
    model = FakeModelClient(
        [
            ModelResponse(
                content=[
                    {"type": "thinking", "thinking": "hmm", "signature": "sig123"},
                    {"type": "text", "text": "here you go"},
                ],
                stop_reason="end_turn",
                usage=Usage(input_tokens=10, output_tokens=5),
            )
        ]
    )
    deps = make_deps(model)

    result, _ = await _run(deps, store, model)

    assistant = next(m for m in result.messages if m["role"] == "assistant")
    assert [b["type"] for b in assistant["content"]] == ["thinking", "text"]
    assert assistant["content"][0]["signature"] == "sig123"


async def test_pause_turn_resumes(make_deps, store):
    model = FakeModelClient(
        [
            ModelResponse(content=[{"type": "text", "text": "…"}], stop_reason="pause_turn"),
            text_response("finished"),
        ]
    )
    deps = make_deps(model)

    result, _ = await _run(deps, store, model)

    assert result.text == "finished"
    assert len(model.calls) == 2


async def test_tool_error_is_recoverable(make_deps, store):
    """A failing tool comes back as data the model can react to, not an
    exception that kills the run."""
    model = FakeModelClient(
        [
            tool_response([("tu_1", "ReadFile", {"path": "missing.txt"})]),
            text_response("that file does not exist yet"),
        ]
    )
    deps = make_deps(model)

    result, _ = await _run(deps, store, model)

    results = next(
        m["content"]
        for m in result.messages
        if m["role"] == "user"
        and isinstance(m["content"], list)
        and m["content"][0].get("type") == "tool_result"
    )
    assert results[0]["is_error"] is True
    assert result.text == "that file does not exist yet"


async def test_unknown_tool_does_not_crash(make_deps, store):
    model = FakeModelClient(
        [
            tool_response([("tu_1", "DoesNotExist", {})]),
            text_response("no such tool, using another approach"),
        ]
    )
    deps = make_deps(model)

    result, _ = await _run(deps, store, model)

    assert result.text.startswith("no such tool")


async def test_status_and_events(make_deps, store):
    model = FakeModelClient([text_response("ok")])
    deps = make_deps(model)

    result, events = await _run(deps, store, model)

    run = await store.get_run(user_id="u1", run_id=result.run_id)
    assert run.status is RunStatus.SUCCEEDED
    types = [e.type for e in events]
    assert types[0] is EventType.RUN_STARTED
    assert types[-1] is EventType.RUN_FINISHED
    assert [e.seq for e in events] == list(range(1, len(events) + 1))

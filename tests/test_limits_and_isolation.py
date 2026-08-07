"""Caps, tenancy, and path containment.

Each cap is driven to its limit with the other two left slack, because a test
that trips all three at once cannot tell you which one is actually wired.
"""

from __future__ import annotations

import time

import pytest

from twin.config import Caps
from twin.errors import PathNotAllowed
from twin.events import EventEmitter, EventType
from twin.harness import run_harness
from twin.limits import RunBudget, estimate_cost_usd
from twin.llm.client import ModelResponse, Usage
from twin.llm.fake import FakeModelClient, text_response, tool_response
from twin.store.base import RunStatus


# -- run caps ---------------------------------------------------------------


async def test_iteration_cap_stops_a_runaway(make_deps, store):
    """Model that never stops calling tools. Time and spend left generous so
    only the iteration cap can be responsible."""
    model = FakeModelClient(
        [tool_response([(f"tu_{i}", "ListDir", {})]) for i in range(50)]
    )
    deps = make_deps(
        model,
        caps=Caps(max_iterations=5, max_wall_clock_s=600, max_spend_usd=1000),
    )

    run = await store.create_run(user_id="u1", session_id="s1")
    result = await run_harness(
        deps=deps,
        user_id="u1",
        session_id="s1",
        run_id=run.id,
        user_message="loop forever",
    )

    assert result.truncated_by == "IterationLimitExceeded"
    assert result.iterations == 5


async def test_spend_cap_stops_a_runaway(make_deps, store):
    expensive = ModelResponse(
        content=[{"type": "tool_use", "id": "tu_x", "name": "ListDir", "input": {}}],
        stop_reason="tool_use",
        model="claude-opus-5",
        usage=Usage(input_tokens=200_000, output_tokens=8_000),
    )
    model = FakeModelClient([expensive] * 20)
    deps = make_deps(
        model,
        caps=Caps(max_iterations=100, max_wall_clock_s=600, max_spend_usd=2.00),
    )

    run = await store.create_run(user_id="u1", session_id="s1")
    result = await run_harness(
        deps=deps,
        user_id="u1",
        session_id="s1",
        run_id=run.id,
        user_message="burn money",
    )

    assert result.truncated_by == "SpendLimitExceeded"
    assert result.spend_usd >= 2.00
    assert result.iterations < 100


async def test_wall_clock_cap_is_independent():
    budget = RunBudget(
        caps=Caps(max_iterations=10_000, max_wall_clock_s=0.05, max_spend_usd=1e9)
    )
    budget.begin_iteration()
    time.sleep(0.06)
    with pytest.raises(Exception) as exc:
        budget.begin_iteration()
    assert "TimeLimitExceeded" in type(exc.value).__name__


def test_cache_reads_are_priced_below_fresh_input():
    fresh = estimate_cost_usd(Usage(input_tokens=100_000), "claude-opus-5")
    cached = estimate_cost_usd(
        Usage(cache_read_input_tokens=100_000), "claude-opus-5"
    )
    assert cached == pytest.approx(fresh * 0.10)


# -- tenancy ----------------------------------------------------------------


async def test_another_tenant_cannot_read_a_run(store):
    run = await store.create_run(user_id="alice", session_id="s1")
    await store.save_messages(
        user_id="alice", run_id=run.id, messages=[{"role": "user", "content": "secret"}]
    )

    assert await store.get_run(user_id="alice", run_id=run.id) is not None
    assert await store.get_run(user_id="mallory", run_id=run.id) is None


async def test_another_tenant_cannot_write_a_run(store):
    run = await store.create_run(user_id="alice", session_id="s1")
    await store.save_messages(
        user_id="mallory", run_id=run.id, messages=[{"role": "user", "content": "pwned"}]
    )

    owned = await store.get_run(user_id="alice", run_id=run.id)
    assert owned.messages == []


async def test_idempotency_key_returns_the_same_run(store):
    first = await store.create_run(
        user_id="u1", session_id="s1", idempotency_key="abc"
    )
    second = await store.create_run(
        user_id="u1", session_id="s1", idempotency_key="abc"
    )
    assert first.id == second.id


async def test_sandboxes_are_namespaced_by_user(tmp_path):
    from twin.sandbox.local import LocalSandboxFactory

    factory = LocalSandboxFactory(tmp_path)
    a = await factory.acquire(user_id="alice", session_id="shared-id")
    b = await factory.acquire(user_id="mallory", session_id="shared-id")

    # Same session id, different tenants: must not be the same directory.
    assert a.root != b.root
    await a.write_file("notes.txt", "alice's data")
    with pytest.raises(Exception):
        await b.read_file("notes.txt")


# -- path containment -------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    ["../escape.txt", "../../etc/passwd", "/etc/passwd", "a/../../../outside.txt"],
)
async def test_path_escapes_are_rejected(sandbox, path):
    with pytest.raises(PathNotAllowed):
        sandbox.resolve(path)


async def test_symlink_escape_is_rejected(sandbox, tmp_path):
    outside = tmp_path / "outside-secret.txt"
    outside.write_text("secret")
    (sandbox.root / "link").symlink_to(outside)

    with pytest.raises(PathNotAllowed):
        sandbox.resolve("link")


async def test_escape_reaches_the_model_as_a_recoverable_error(make_deps, store):
    """The model should get an error it can react to, not a crashed run."""
    model = FakeModelClient(
        [
            tool_response([("tu_1", "ReadFile", {"path": "../../etc/passwd"})]),
            text_response("can't reach that, staying in the workspace"),
        ]
    )
    deps = make_deps(model)

    run = await store.create_run(user_id="u1", session_id="s1")
    result = await run_harness(
        deps=deps,
        user_id="u1",
        session_id="s1",
        run_id=run.id,
        user_message="read /etc/passwd",
    )

    results = next(
        m["content"]
        for m in result.messages
        if m["role"] == "user"
        and isinstance(m["content"], list)
        and m["content"][0].get("type") == "tool_result"
    )
    assert results[0]["is_error"] is True
    assert "outside the workspace" in results[0]["content"]
    stored = await store.get_run(user_id="u1", run_id=run.id)
    assert stored.status is RunStatus.SUCCEEDED

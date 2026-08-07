from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from twin.config import Caps  # noqa: E402
from twin.harness import HarnessDeps  # noqa: E402
from twin.persona import Persona, StyleSample, build_system_prompt  # noqa: E402
from twin.sandbox.local import LocalSandboxFactory  # noqa: E402
from twin.store.memory import InMemoryStore  # noqa: E402
from twin.tools.registry import default_registry  # noqa: E402


@pytest.fixture
def persona() -> Persona:
    return Persona(
        name="Test User",
        summary="Writes tersely.",
        samples=(StyleSample(context="chat", text="yeah that works, ship it"),),
    )


@pytest.fixture
def store() -> InMemoryStore:
    return InMemoryStore()


@pytest.fixture
async def sandbox(tmp_path):
    factory = LocalSandboxFactory(tmp_path / "workspaces")
    sb = await factory.acquire(user_id="u1", session_id="s1")
    yield sb
    await sb.close()


@pytest.fixture
def make_deps(store, sandbox, persona):
    def _make(model, **overrides):
        base = dict(
            model=model,
            registry=default_registry(),
            store=store,
            sandbox=sandbox,
            system_prompt=build_system_prompt(persona),
            caps=Caps(max_iterations=10, max_wall_clock_s=30, max_spend_usd=1.0),
        )
        base.update(overrides)
        return HarnessDeps(**base)

    return _make

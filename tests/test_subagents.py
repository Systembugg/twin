import pytest
from twin.tools.registry import default_registry
from twin.subagent.runner import run_subagent
from twin.store.memory import InMemoryStore
from twin.sandbox.local import LocalSandboxFactory
from twin.persona import build_system_prompt
from twin.runtime.personas import persona_from_row
from twin.harness import HarnessDeps
from twin.llm.factory import build_model_client, build_summariser
from twin.config import Settings
from twin.hooks import HookRegistry, PermissionMode, PermissionPolicy
from twin.llm.fake import FakeModelClient, text_response


def test_subagent_tool_opt_in_flag():
    # By default, subagents are DISABLED (0 extra tokens, 0 risk)
    reg_default = default_registry(enable_subagents=False)
    assert "SubAgentSpawn" not in reg_default.names()

    # When explicitly enabled, SubAgentSpawn IS registered
    reg_enabled = default_registry(enable_subagents=True)
    assert "SubAgentSpawn" in reg_enabled.names()


@pytest.mark.asyncio
async def test_subagent_execution_creates_isolated_subsession():
    settings = Settings.from_env()
    store = InMemoryStore()
    user_id = "test_user_sub"
    parent_session_id = "parent_session_123"

    persona = persona_from_row(user_id, {"name": "Test Persona", "summary": "Tester"})
    sandbox_factory = LocalSandboxFactory(settings.workspace_root)
    sandbox = await sandbox_factory.acquire(user_id=user_id, session_id=parent_session_id)

    fake_model = FakeModelClient([text_response("Subagent Research Completed")])
    deps = HarnessDeps(
        model=fake_model,
        summariser=build_summariser(settings),
        registry=default_registry(enable_subagents=True),
        store=store,
        sandbox=sandbox,
        system_prompt=build_system_prompt(persona),
        caps=settings.caps,
        hooks=HookRegistry(),
        permissions=PermissionPolicy(PermissionMode.AUTO),
    )

    # Execute subagent
    output = await run_subagent(
        deps=deps,
        user_id=user_id,
        parent_session_id=parent_session_id,
        role="Researcher",
        task_prompt="Say 'Subagent Research Completed'",
        max_iterations=1,
    )

    await sandbox.close()
    assert isinstance(output, str)
    assert len(output) > 0

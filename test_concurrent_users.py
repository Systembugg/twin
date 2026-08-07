import asyncio
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from twin.config import Settings
from twin.harness import HarnessDeps, run_harness
from twin.hooks import HookRegistry, PermissionMode, PermissionPolicy
from twin.llm.factory import build_model_client, build_summariser
from twin.persona import build_system_prompt
from twin.runtime.personas import persona_from_row
from twin.sandbox.local import LocalSandboxFactory
from twin.store.memory import InMemoryStore
from twin.tools.registry import default_registry


async def fn_run_user_task(user_id: str, prompt: str, store: InMemoryStore, settings: Settings):
    persona = persona_from_row(user_id, {"name": user_id, "summary": "Test User"})
    sandbox_factory = LocalSandboxFactory(settings.workspace_root)
    sandbox = await sandbox_factory.acquire(user_id=user_id, session_id="session_1")

    deps = HarnessDeps(
        model=build_model_client(settings),
        summariser=build_summariser(settings),
        registry=default_registry(),
        store=store,
        sandbox=sandbox,
        system_prompt=build_system_prompt(persona),
        caps=settings.caps,
        hooks=HookRegistry(),
        permissions=PermissionPolicy(PermissionMode.AUTO),
    )

    run = await store.create_run(user_id=user_id, session_id="session_1")
    result = await run_harness(
        deps=deps,
        user_id=user_id,
        session_id="session_1",
        run_id=run.id,
        user_message=prompt,
        history=[],
    )
    await sandbox.close()
    return result, sandbox.root


async def main():
    settings = Settings.from_env()
    store = InMemoryStore()

    print("=== Starting simultaneous execution for User Alpha and User Beta ===")

    task_a = fn_run_user_task(
        user_id="user_alpha",
        prompt="create a file alpha_notes.txt with text 'SECRET_ALPHA_123'",
        store=store,
        settings=settings,
    )

    task_b = fn_run_user_task(
        user_id="user_beta",
        prompt="create a file beta_notes.txt with text 'SECRET_BETA_999'",
        store=store,
        settings=settings,
    )

    # Run simultaneously with asyncio.gather
    (res_a, root_a), (res_b, root_b) = await asyncio.gather(task_a, task_b)

    print(f"User Alpha Completed. Workspace: {root_a}")
    print(f"   Response: {res_a.text.strip()}\n")

    print(f"User Beta Completed. Workspace: {root_b}")
    print(f"   Response: {res_b.text.strip()}\n")

    # VERIFY WORKSPACE ISOLATION
    files_a = [f.name for f in Path(root_a).glob("*")]
    files_b = [f.name for f in Path(root_b).glob("*")]

    print("=== ISOLATION VERIFICATION ===")
    print(f"User Alpha Workspace Files: {files_a}")
    print(f"User Beta  Workspace Files: {files_b}\n")

    # Assertions
    assert "alpha_notes.txt" in files_a, "alpha_notes.txt missing from User Alpha!"
    assert "beta_notes.txt" not in files_a, "SECURITY LEAK: beta_notes.txt found in User Alpha workspace!"

    assert "beta_notes.txt" in files_b, "beta_notes.txt missing from User Beta!"
    assert "alpha_notes.txt" not in files_b, "SECURITY LEAK: alpha_notes.txt found in User Beta workspace!"

    print("SUCCESS: MULTI-USER SIMULTANEOUS ISOLATION VERIFIED 100% SUCCESSFUL!")

if __name__ == "__main__":
    asyncio.run(main())

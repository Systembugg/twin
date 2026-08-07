import asyncio
import os
import time
from pathlib import Path
from dotenv import load_dotenv
import jwt

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


async def execute_user_llm_task(user_id: str, prompt: str, store: InMemoryStore, settings: Settings):
    persona = persona_from_row(user_id, {"name": user_id, "summary": "Concurrent Test User"})
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

    print(f"[{user_id}] Starting LLM task: '{prompt}'")
    result = await run_harness(
        deps=deps,
        user_id=user_id,
        session_id="session_1",
        run_id=run.id,
        user_message=prompt,
        history=[],
    )
    await sandbox.close()
    return user_id, result, sandbox.root


async def main():
    settings = Settings.from_env()
    store = InMemoryStore()

    print("=== Starting 3 Concurrent LLM Task Executions ===\n")

    # 3 distinct tasks for 3 distinct users
    t1 = execute_user_llm_task("user_python", "create file_python.txt with a 2-line poem about Python", store, settings)
    t2 = execute_user_llm_task("user_rust", "create file_rust.txt with a 2-line poem about Rust", store, settings)
    t3 = execute_user_llm_task("user_linux", "create file_linux.txt with a 2-line poem about Linux", store, settings)

    # Execute all 3 concurrently in parallel
    results = await asyncio.gather(t1, t2, t3)

    print("\n=== All 3 Tasks Completed! Output Verification ===")
    for uid, res, root in results:
        files = [f.name for f in Path(root).glob("*")]
        print(f"\nUser: {uid}")
        print(f"  Workspace: {root}")
        print(f"  Files created in workspace: {files}")
        print(f"  AI Response: {res.text.strip()}")

    # Strict isolation assertions
    root_p = results[0][2]
    root_r = results[1][2]
    root_l = results[2][2]

    files_p = [f.name for f in Path(root_p).glob("*")]
    files_r = [f.name for f in Path(root_r).glob("*")]
    files_l = [f.name for f in Path(root_l).glob("*")]

    assert "file_python.txt" in files_p and "file_rust.txt" not in files_p and "file_linux.txt" not in files_p
    assert "file_rust.txt" in files_r and "file_python.txt" not in files_r and "file_linux.txt" not in files_r
    assert "file_linux.txt" in files_l and "file_python.txt" not in files_l and "file_rust.txt" not in files_l

    print("\nSUCCESS: All 3 distinct LLM tasks executed concurrently with 100% accurate file creation & zero workspace crossover!")


if __name__ == "__main__":
    asyncio.run(main())

import asyncio
import os
import time
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


from dataclasses import replace

async def main():
    settings = Settings.from_env()
    store = InMemoryStore()

    user_id = "goal_test_user"
    session_id = "goal_session_1"
    prompt = (
        "hey build me a small static blog generator in python. "
        "put some markdown posts in a folder with titles, dates, and tags, "
        "render styled html pages and an index page listing all posts sorted by date, "
        "write a python test script with plain asserts to verify it works, "
        "run the tests to make sure they pass, and write a readme with usage instructions."
    )

    print("==================================================")
    print("Starting 'Plan and Run Till Goal' Autonomous Agent")
    print("==================================================\n")
    print(f"User Prompt: '{prompt}'\n")

    persona = persona_from_row(user_id, {"name": "Senior Software Agent", "summary": "Autonomous Developer"})
    sandbox_factory = LocalSandboxFactory(settings.workspace_root)
    sandbox = await sandbox_factory.acquire(user_id=user_id, session_id=session_id)

    caps = replace(settings.caps, max_iterations=12)

    deps = HarnessDeps(
        model=build_model_client(settings),
        summariser=build_summariser(settings),
        registry=default_registry(),
        store=store,
        sandbox=sandbox,
        system_prompt=build_system_prompt(persona),
        caps=caps,
        hooks=HookRegistry(),
        permissions=PermissionPolicy(PermissionMode.AUTO),
    )

    run = await store.create_run(user_id=user_id, session_id=session_id)

    start_time = time.time()
    result = await run_harness(
        deps=deps,
        user_id=user_id,
        session_id=session_id,
        run_id=run.id,
        user_message=prompt,
        history=[],
    )
    elapsed = time.time() - start_time
    await sandbox.close()

    print("\n==================================================")
    print("AUTONOMOUS AGENT GOAL EXECUTION SUMMARY")
    print("==================================================")
    print(f"Total Turn Iterations Taken: {result.iterations}")
    print(f"Total Autonomous Time:      {elapsed:.2f} seconds")
    print(f"Agent Final Response:       \n{result.text.strip()}\n")

    workspace = Path(sandbox.root)
    files = [str(p.relative_to(workspace)) for p in workspace.rglob("*") if p.is_file()]

    print("==================================================")
    print(f"Files Created in Agent Workspace ({workspace}):")
    for f in files:
        print(f"  - {f}")
    print("==================================================\n")

    print("SUCCESS: Autonomous 'Plan and Run Till Goal' execution completed!")


if __name__ == "__main__":
    asyncio.run(main())

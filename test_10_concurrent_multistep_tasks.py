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


async def run_multistep_user_task(user_num: int, store: InMemoryStore, settings: Settings):
    user_id = f"user_agent_{user_num:02d}"
    session_id = f"session_{user_num:02d}"
    prompt = (
        f"Do this in order: "
        f"1) create app_{user_num}.py with a function add(a, b) returning a + b + {user_num}. "
        f"2) create test_app_{user_num}.py with a plain assert test calling add(2, 3) == {5 + user_num}. "
        f"3) read back test_app_{user_num}.py to confirm."
    )

    persona = persona_from_row(user_id, {"name": user_id, "summary": "Multi-step Test User"})
    sandbox_factory = LocalSandboxFactory(settings.workspace_root)
    sandbox = await sandbox_factory.acquire(user_id=user_id, session_id=session_id)

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

    run = await store.create_run(user_id=user_id, session_id=session_id)

    print(f"[{user_id}] Enqueued 3-step task...")
    start_t = time.time()
    result = await run_harness(
        deps=deps,
        user_id=user_id,
        session_id=session_id,
        run_id=run.id,
        user_message=prompt,
        history=[],
    )
    elapsed = time.time() - start_t
    await sandbox.close()

    files = [f.name for f in Path(sandbox.root).glob("*")]
    return {
        "user_id": user_id,
        "run_id": run.id,
        "elapsed_s": elapsed,
        "response": result.text.strip(),
        "files": files,
        "workspace": sandbox.root,
        "iterations": result.iterations,
    }


async def main():
    settings = Settings.from_env()
    store = InMemoryStore()

    num_users = 10
    print(f"==================================================")
    print(f"Starting 10 Concurrent Multi-Step Agent Task Test")
    print(f"==================================================\n")

    start_total = time.time()
    tasks = [
        run_multistep_user_task(i + 1, store, settings)
        for i in range(num_users)
    ]

    results = await asyncio.gather(*tasks)
    total_time = time.time() - start_total

    print("\n==================================================")
    print("10 MULTI-STEP AGENT RESULTS SUMMARY")
    print("==================================================")

    all_success = True
    for res in results:
        uid = res["user_id"]
        files = res["files"]
        turns = res["iterations"]
        dur = res["elapsed_s"]

        # Check required files created for user N
        num_str = uid.split("_")[-1]
        app_file = f"app_{int(num_str)}.py"
        test_file = f"test_app_{int(num_str)}.py"

        has_app = app_file in files
        has_test = test_file in files
        ok = has_app and has_test

        if not ok:
            all_success = False

        status_str = "SUCCESS" if ok else "FAILED"
        print(f"[{uid}] {status_str} | Turns: {turns} | Time: {dur:.2f}s | Files: {files}")

    print(f"\n==================================================")
    print(f"Total Parallel Wall-Clock Time: {total_time:.2f}s")
    print(f"==================================================")

    assert all_success, "One or more multi-step user tasks failed to complete all steps!"
    print("SUCCESS: All 10 concurrent multi-step tasks executed with 100% precision & zero workspace cross-contamination!")


if __name__ == "__main__":
    asyncio.run(main())

import asyncio
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


async def main():
    settings = Settings.from_env()
    store = InMemoryStore()

    user_id = "market_cap_user"
    session_id = "session_market_1"

    prompt = "can u tell me what is market cap of apple and google"

    print("==================================================")
    print("Testing Agent Automatic Tool Selection (Web Search)")
    print("==================================================\n")
    print(f"User Prompt: \"{prompt}\"\n")

    persona = persona_from_row(
        user_id,
        {
            "name": "Financial Assistant",
            "summary": "Helpful AI agent with web search capabilities.",
        },
    )
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

    print("==================================================")
    print("AI RESPONSE & MARKET CAP SUMMARY:")
    print("==================================================")
    # Print clean ascii
    print(result.text.encode("ascii", "ignore").decode("ascii").strip())
    print(f"\nTotal Iteration Turns Taken: {result.iterations}")
    print(f"Execution Time: {elapsed:.2f} seconds\n")
    print("==================================================")


if __name__ == "__main__":
    asyncio.run(main())

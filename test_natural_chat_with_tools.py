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

    user_id = "casual_talk_user"
    session_id = "session_casual_1"

    # Natural human conversation prompt mixing casual talk & tool requests
    prompt = (
        "Hey! How's it going today? I'm having a great afternoon working on our project. "
        "Could you create a quick file named `friendly_note.txt` with a warm 2-sentence note "
        "encouraging developers, and then let me know what files are in our workspace folder?"
    )

    print("==================================================")
    print("Testing Natural Human Conversation with Tool Calls")
    print("==================================================\n")
    print(f"User Message: \"{prompt}\"\n")

    persona = persona_from_row(
        user_id,
        {
            "name": "Alex",
            "summary": "Friendly, helpful AI teammate who chats naturally and works efficiently.",
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
    print("AI NATURAL CONVERSATION & TOOL RESPONSE:")
    print("==================================================")
    print(result.text.strip())
    print(f"\nTotal Iteration Turns Taken: {result.iterations}")
    print(f"Execution Time: {elapsed:.2f} seconds\n")

    # Read created file
    workspace = Path(sandbox.root)
    created_file = workspace / "friendly_note.txt"

    if created_file.exists():
        print("==================================================")
        print(f"Created File Content ({created_file.name}):")
        print("==================================================")
        print(created_file.read_text(encoding="utf-8").strip())
        print("==================================================\n")
        print("SUCCESS: Natural conversation + tool calls executed perfectly!")
    else:
        print("FAIL: File friendly_note.txt was not created.")


if __name__ == "__main__":
    asyncio.run(main())

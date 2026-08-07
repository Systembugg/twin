"""Single-process CLI.

No Redis, no Postgres, no queue — the same `run_harness` the workers call,
wired to the in-memory store and a local sandbox. This is how you test the
voice and the loop before any infrastructure exists.

    python -m twin.cli --persona persona.example.json --workspace ./scratch
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from twin.config import Settings
from twin.events import Event, EventEmitter, EventType
from twin.harness import HarnessDeps, run_harness
from twin.hooks import HookRegistry, PermissionMode, PermissionPolicy
from twin.llm.factory import build_model_client, build_summariser, missing_credentials
from twin.persona import build_system_prompt
from twin.runtime.personas import persona_from_row
from twin.sandbox.local import LocalSandboxFactory
from twin.store.memory import InMemoryStore
from twin.tools.registry import default_registry

_DIM = "\033[2m"
_BOLD = "\033[1m"
_RED = "\033[31m"
_OFF = "\033[0m"


async def _print_event(event: Event) -> None:
    d = event.data
    if event.type is EventType.TOOL_CALL:
        args = json.dumps(d.get("args", {}))[:140]
        print(f"{_DIM}  → {d.get('tool')}({args}){_OFF}", file=sys.stderr)
    elif event.type is EventType.TOOL_RESULT:
        mark = f"{_RED}✗{_OFF}" if d.get("is_error") else "✓"
        print(
            f"{_DIM}  {mark} {d.get('tool')} {d.get('duration_s')}s{_OFF}",
            file=sys.stderr,
        )
    elif event.type is EventType.TOOL_DENIED:
        print(f"{_RED}  ✗ denied: {d.get('reason')}{_OFF}", file=sys.stderr)
    elif event.type is EventType.COMPACTED:
        print(f"{_DIM}  … compacted {d.get('summarised_messages')} messages{_OFF}", file=sys.stderr)
    elif event.type is EventType.RUN_FINISHED:
        print(
            f"{_DIM}  [{d.get('iterations')} turns · ${d.get('spend_usd', 0):.4f} · "
            f"cache read {d.get('cache_read_input_tokens', 0)}]{_OFF}",
            file=sys.stderr,
        )
    elif event.type is EventType.RUN_FAILED:
        print(f"{_RED}  run failed: {d.get('message')}{_OFF}", file=sys.stderr)


async def chat(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    overrides: dict[str, object] = {}
    if args.workspace:
        overrides["workspace_root"] = args.workspace
    if args.base_url:
        overrides["base_url"] = args.base_url
    if args.model:
        overrides["model"] = args.model
    if overrides:
        settings = Settings(**{**settings.__dict__, **overrides})

    problem = missing_credentials(settings)
    if problem:
        print(problem, file=sys.stderr)
        return 1

    persona_raw = json.loads(Path(args.persona).read_text("utf-8"))
    persona = persona_from_row(args.user, persona_raw)
    if not persona.samples:
        print(
            f"{_DIM}Warning: persona has no style samples. The voice will be "
            f"generic — add 15-20 real messages.{_OFF}",
            file=sys.stderr,
        )

    store = InMemoryStore()
    sandbox = await LocalSandboxFactory(settings.workspace_root).acquire(
        user_id=args.user, session_id=args.session
    )
    print(f"{_DIM}workspace: {sandbox.root}{_OFF}", file=sys.stderr)

    deps = HarnessDeps(
        model=build_model_client(settings),
        summariser=build_summariser(settings),
        registry=default_registry(),
        store=store,
        sandbox=sandbox,
        system_prompt=build_system_prompt(persona),
        caps=settings.caps,
        hooks=HookRegistry(),
        permissions=PermissionPolicy(PermissionMode(args.permission_mode)),
    )

    history: list[dict] = []
    try:
        while True:
            try:
                user_input = input(f"{_BOLD}you ›{_OFF} ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return 0
            if not user_input:
                continue
            if user_input in ("/quit", "/exit"):
                return 0

            run = await store.create_run(user_id=args.user, session_id=args.session)
            result = await run_harness(
                deps=deps,
                user_id=args.user,
                session_id=args.session,
                run_id=run.id,
                user_message=user_input,
                history=history,
                emitter=EventEmitter(run.id, sink=_print_event),
            )
            history = result.messages
            print(f"\n{result.text}\n")
    finally:
        await sandbox.close()


def main() -> int:
    parser = argparse.ArgumentParser(prog="twin")
    parser.add_argument("--persona", default="persona.example.json")
    parser.add_argument("--user", default="local")
    parser.add_argument("--session", default="cli")
    parser.add_argument("--workspace", default=None)
    parser.add_argument(
        "--base-url",
        default=None,
        help="OpenAI-protocol endpoint: a shorthand (groq, ollama, vllm, "
        "openrouter, together, lmstudio) or a full URL. Omit for Anthropic.",
    )
    parser.add_argument("--model", default=None, help="Override TWIN_MODEL.")
    parser.add_argument(
        "--permission-mode", default="auto", choices=[m.value for m in PermissionMode]
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s %(message)s",
    )
    return asyncio.run(chat(args))


if __name__ == "__main__":
    raise SystemExit(main())

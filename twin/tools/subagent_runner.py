"""SubAgent runner — executes child harness loops concurrently."""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import replace
from typing import Any

from twin.config import Caps
from twin.harness import HarnessDeps, RunResult, run_harness
from twin.events import EventEmitter
from twin.tools.base import ToolContext

log = logging.getLogger(__name__)


async def run_subagents(
    subtasks: list[dict[str, Any]],
    ctx: ToolContext,
) -> list[dict[str, Any]]:
    """Run multiple child agents concurrently, each with its own harness loop.

    Each child agent:
    - Gets its own run_id (prefixed with 'sub-')
    - Shares the parent's sandbox (same workspace directory)
    - Has a reduced iteration cap
    - Has NO ability to spawn further subagents (prevents infinite recursion)
    """
    # These are injected by the parent's _execute method via ctx.extras
    parent_deps: HarnessDeps = ctx.extras["harness_deps"]
    parent_user_id: str = ctx.user_id
    parent_session_id: str = ctx.session_id

    # Build child deps — same model, same sandbox, but:
    # 1. Reduced caps
    # 2. Registry WITHOUT SubAgentSpawn (prevent recursion)
    from twin.tools.registry import default_registry

    child_registry = default_registry(exclude={"SubAgentSpawn"})

    async def _run_one(subtask: dict[str, Any]) -> dict[str, Any]:
        sub_id = subtask["id"]
        sub_prompt = subtask["prompt"]
        max_iter = subtask.get("max_iterations", 10)
        sub_run_id = f"sub-{uuid.uuid4().hex[:12]}"

        child_caps = replace(
            parent_deps.caps,
            max_iterations=min(max_iter, 15),  # Hard cap at 15 for children
            max_spend_usd=min(parent_deps.caps.max_spend_usd * 0.3, 0.50),
        )

        child_deps = HarnessDeps(
            model=parent_deps.model,
            summariser=parent_deps.summariser,
            registry=child_registry,
            store=parent_deps.store,
            sandbox=parent_deps.sandbox,  # Shared sandbox
            system_prompt=parent_deps.system_prompt,
            caps=child_caps,
            hooks=parent_deps.hooks,
        )

        try:
            result: RunResult = await run_harness(
                deps=child_deps,
                user_id=parent_user_id,
                session_id=parent_session_id,
                run_id=sub_run_id,
                user_message=sub_prompt,
                history=[],  # Fresh context for each child
            )
            return {
                "id": sub_id,
                "output": result.text[:5000],  # Cap output size
                "iterations": result.iterations,
                "error": None,
            }
        except Exception as e:
            log.exception("Subtask %s failed", sub_id)
            return {
                "id": sub_id,
                "output": str(e),
                "iterations": 0,
                "error": str(e),
            }

    # Run all subtasks concurrently
    results = await asyncio.gather(*[_run_one(st) for st in subtasks])
    return list(results)

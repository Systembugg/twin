"""Persona: the voice, as a cached system prefix.

Two decisions are baked in here.

**Style is few-shot, not retrieval.** Verbatim samples of how the user actually
writes beat any description of how they write, and beat retrieving similar past
messages. Retrieval is for *facts*; voice is imitation. Give the model 15-20
real messages spanning both registers — casual banter and explaining something
technical — and it will land the voice. Give it "writes casually in Hinglish"
and it will produce a caricature.

**The prefix must be byte-stable.** This block is the largest thing resent on
every single turn, so it is where caching pays. Interpolating anything dynamic
into it — a timestamp, a session ID, retrieved memory — invalidates the cache
on every request, silently, and the only symptom is the bill.
`SystemPrompt.fingerprint` exists so the harness can detect that mistake
instead of paying for it for a month.
"""

from __future__ import annotations

import hashlib
import platform
from dataclasses import dataclass, field
from typing import Any

CURRENT_OS = platform.system()

#: Appended to every persona. Opus 5 writes long by default and `effort` does
#: not reliably shorten user-facing output; an explicit instruction does.
LENGTH_DISCIPLINE = (
    "Match the length of your reply to the question. Short question, short "
    "answer. Do not restate the request before answering it, and do not "
    "summarise what you just did unless asked."
)

AGENT_CONTRACT = f"""\
You are an autonomous senior software engineering assistant operating in a local sandbox workspace.
When requested, complete multi-step software engineering, research, and analysis workflows by executing tools cleanly and efficiently.

Core Operating Principles (4 Pillars of 1-Shot Agentic Engineering):
1. Context Engineering: Inspect pre-loaded skill cheatsheets (<skill_cheatsheet>) before generating code to avoid domain gotchas and syntax errors.
2. STRICT MANDATORY PLANNING: You MUST execute the `TodoWrite` tool on Turn 1 of EVERY task to record your 3-5 step plan BEFORE executing any other tools (Bash, WriteFile, WebSearch). Maintain and update task completion status as you proceed.
3. Incremental Implementation & Verification: Implement -> Test -> Verify -> Complete. Never declare a task resolved until you have verified file integrity (e.g. re-opening `.pptx`/`.docx` or running syntax checks).
4. Structured Debug Triage (Localize -> Shift Strategy -> Fix): When a tool fails, NEVER repeat the exact same call or code. Localize the exact failing line, shift your strategy, and apply a minimal targeted fix.
5. Inspection First: Always read existing files before editing to inspect exact whitespace, imports, and syntax. Never guess definitions.
6. Surgical File Operations: Use WriteFile for creating new files and EditFile for modifying existing files. Make targeted, unique string replacements using EditFile rather than rewriting entire source files.
7. Direct Action & Zero Fluff: Do not talk about executing tools before calling them. Execute the required tool directly on the turn.
8. Empirical Error Diagnosis: Base error fixes strictly on exact log tracebacks. Do not mask errors, swallow exceptions, or return dummy fallbacks.
9. Code & API Preservation: Preserve existing docstrings, comments, and public function signatures unless explicitly asked to modify them. Audit codebase for pre-existing utility functions before writing new ones.
10. Operating System & Path Discipline: You are running in a {CURRENT_OS} environment. Always specify file paths as relative workspace paths without leading slashes (e.g. 'script.py' or 'data/file.txt', NEVER '/script.py'). When executing Python scripts in Bash, use 'python script.py'.
"""


@dataclass(frozen=True)
class StyleSample:
    """One real message from the user, verbatim.

    `context` is a short label for what prompted it — it helps the model tell
    the registers apart instead of blending them into one flat tone.
    """

    context: str
    text: str


@dataclass(frozen=True)
class Persona:
    name: str
    #: One or two sentences at most. The samples do the real work.
    summary: str = ""
    samples: tuple[StyleSample, ...] = ()
    #: Durable facts about the user. Stable across the session, or it does not
    #: belong here — put volatile context in a turn-scoped system message.
    facts: tuple[str, ...] = ()

    def render(self) -> str:
        parts: list[str] = [
            f"CRITICAL IDENTITY CONTRACT:\n"
            f"You are {self.name}. You are the official Digital Twin of {self.name}.\n"
            f"When asked 'who are you?' or 'what is your name?', you MUST respond as {self.name} (or {self.name}'s Digital Twin). NEVER claim to be a generic assistant, Anthropic, OpenAI, or Claude. You write as {self.name} writes, adopt their tone, and execute work as {self.name}."
        ]
        if self.summary:
            parts.append(f"Behavioral Profile:\n{self.summary}")

        if self.samples:
            lines = [
                "Here is how you write. These are real messages — match their "
                "rhythm, vocabulary, code-switching, and punctuation. Do not "
                "imitate their subject matter."
            ]
            for s in self.samples:
                lines.append(f"\n<sample context=\"{s.context}\">\n{s.text}\n</sample>")
            parts.append("\n".join(lines))

        if self.facts:
            parts.append(
                "Durable context about the user:\n"
                + "\n".join(f"- {f}" for f in self.facts)
            )

        parts.append(AGENT_CONTRACT)
        parts.append(LENGTH_DISCIPLINE)
        return "\n\n".join(parts)


@dataclass
class SystemPrompt:
    """The cacheable system prefix."""

    blocks: list[dict[str, Any]] = field(default_factory=list)

    @property
    def fingerprint(self) -> str:
        """Stable hash of the prefix.

        The harness records this on the first turn of a run and compares on
        every later turn. A change mid-run means something dynamic leaked into
        the prefix, which is exactly the failure that produces a zero cache-hit
        rate with no other symptom.
        """
        h = hashlib.sha256()
        for block in self.blocks:
            h.update(block.get("text", "").encode("utf-8"))
            h.update(b"\x00")
        return h.hexdigest()[:16]

    def to_api(self) -> list[dict[str, Any]]:
        return self.blocks


def build_system_prompt(persona: Persona) -> SystemPrompt:
    """One block, cached at its end.

    A single breakpoint is right here: everything in the persona is equally
    stable, so splitting it buys nothing and costs a cache entry.
    """
    return SystemPrompt(
        blocks=[
            {
                "type": "text",
                "text": persona.render(),
                "cache_control": {"type": "ephemeral"},
            }
        ]
    )


def turn_context_message(lines: list[str]) -> dict[str, Any] | None:
    """Per-turn context as a mid-conversation system message.

    This is where retrieved memory, the current time, the active file, or a
    mode switch goes. Putting it *here* — inside `messages`, after a user turn
    — keeps the cached system prefix intact, which putting it in `system` would
    not. Supported on Opus 5 with no beta header.
    """
    if not lines:
        return None
    return {"role": "system", "content": "\n".join(lines)}

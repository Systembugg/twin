"""Skill Manager and Context Engineering Auto-Loader.

Scans twin/skills/ directory for domain cheatsheets and injects relevant
pre-loaded knowledge into the model's context BEFORE code generation.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


class SkillManager:
    """Discovers, indexes, and matches skills based on prompt intent."""

    def __init__(self, skills_dir: Path | str | None = None) -> None:
        if skills_dir is None:
            skills_dir = Path(__file__).parent
        self.skills_dir = Path(skills_dir)
        self.skills_dir.mkdir(parents=True, exist_ok=True)

    def list_skills(self) -> list[Path]:
        """Returns all markdown skill files in the skills directory."""
        if not self.skills_dir.exists():
            return []
        skills = list(self.skills_dir.glob("*.md"))
        skills.extend(self.skills_dir.glob("*/SKILL.md"))
        return sorted(skills)

    def get_relevant_skills(self, user_prompt: str) -> str:
        """Matches user prompt keywords against available skills and returns formatted context."""
        prompt_lower = user_prompt.lower()
        matched_content: list[str] = []

        skill_files = self.list_skills()
        for skill_file in skill_files:
            skill_name = skill_file.stem.lower()
            if skill_name == "skill":
                skill_name = skill_file.parent.name.lower()

            keywords = self._extract_keywords(skill_name)
            if any(kw in prompt_lower for kw in keywords):
                try:
                    text = skill_file.read_text(encoding="utf-8", errors="ignore").strip()
                    if text:
                        matched_content.append(
                            f"\n<skill_cheatsheet name=\"{skill_name}\">\n{text}\n</skill_cheatsheet>"
                        )
                except Exception as exc:
                    log.warning("Could not read skill file %s: %s", skill_file, exc)

        if not matched_content:
            return ""

        header = (
            "PRE-LOADED DOMAIN KNOWLEDGE & CHEATSHEETS (Read BEFORE writing code):\n"
            "Apply these proven patterns, gotchas, and templates for this task:\n"
        )
        return header + "\n".join(matched_content)

    def _extract_keywords(self, skill_name: str) -> list[str]:
        """Map skill name to intent keywords."""
        base = skill_name.replace("_skill", "").replace("-skill", "").replace("_", " ")
        keywords = [base]

        if "pptx" in base or "ppt" in base or "presentation" in base:
            keywords.extend(["ppt", "pptx", "slide", "slides", "presentation", "powerpoint"])
        if "docx" in base or "doc" in base or "word" in base:
            keywords.extend(["doc", "docx", "word", "document", "report"])
        if "excel" in base or "xlsx" in base or "csv" in base:
            keywords.extend(["excel", "xlsx", "csv", "spreadsheet", "sheet"])
        if "bash" in base or "shell" in base or "script" in base:
            keywords.extend(["bash", "shell", "script", "terminal", "command"])
        if "react" in base or "frontend" in base:
            keywords.extend(["react", "jsx", "tsx", "frontend", "dashboard", "component"])

        return keywords

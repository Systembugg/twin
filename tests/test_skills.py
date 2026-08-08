"""Verification test for SkillManager auto-loader and context engineering skill injection."""

from pathlib import Path
from twin.skills.manager import SkillManager


def test_skill_manager_discovery_and_matching(tmp_path: Path):
    # Create sample skill file
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "pptx_skill.md").write_text(
        "# PPTX Skill Cheatsheet\nGotcha: Use python-pptx script generator.",
        encoding="utf-8"
    )

    manager = SkillManager(skills_dir=skills_dir)

    # Test discovery
    skills = manager.list_skills()
    assert len(skills) == 1
    assert skills[0].name == "pptx_skill.md"

    # Test keyword matching for presentation intent
    context = manager.get_relevant_skills("Can you build a PowerPoint presentation for stock market?")
    assert "PPTX Skill Cheatsheet" in context
    assert "<skill_cheatsheet name=\"pptx_skill\">" in context

    # Test non-matching intent
    unmatched_context = manager.get_relevant_skills("Hello how are you doing today?")
    assert unmatched_context == ""

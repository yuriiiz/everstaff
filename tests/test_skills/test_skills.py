"""Tests for the skills system."""

import asyncio
import tempfile
from pathlib import Path

from everstaff.skills.manager import SkillManager


def _create_test_skill(tmpdir: Path, name: str, description: str, body: str) -> None:
    skill_dir = tmpdir / name
    skill_dir.mkdir()
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(f"---\nname: {name}\ndescription: {description}\n---\n\n{body}")


def test_skill_discovery():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        _create_test_skill(tmpdir, "test-skill", "A test skill", "# Test\n\nInstructions here.")

        mgr = SkillManager([str(tmpdir)])
        skills = mgr.list()

        assert len(skills) == 1
        assert skills[0].name == "test-skill"
        assert skills[0].description == "A test skill"


def test_skill_content_loading():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        _create_test_skill(tmpdir, "my-skill", "My skill desc", "# My Skill\n\nDo stuff.")

        mgr = SkillManager([str(tmpdir)])
        content = mgr.get("my-skill")

        assert content.metadata.name == "my-skill"
        assert "Do stuff" in content.instructions


def test_skill_manager_metadata_prompt():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        _create_test_skill(tmpdir, "skill-a", "Skill A description", "Body A")
        _create_test_skill(tmpdir, "skill-b", "Skill B description", "Body B")

        manager = SkillManager(
            skills_dirs=[str(tmpdir)],
            active_skill_names=["skill-a"],
        )

        prompt = manager.get_prompt_injection()
        assert "skill-a" in prompt
        assert "Skill A description" in prompt
        # skill-b should not be in the prompt since it's not active
        assert "skill-b" not in prompt


def test_skill_activation():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        _create_test_skill(tmpdir, "activatable", "Activatable skill", "# Activated!\n\nFull instructions here.")

        manager = SkillManager(
            skills_dirs=[str(tmpdir)],
            active_skill_names=["activatable"],
        )

        result = asyncio.run(manager.activate_skill("activatable"))
        assert "Full instructions here" in result


def test_use_skill_tool_creation():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        _create_test_skill(tmpdir, "tool-skill", "Tool skill", "Instructions")

        manager = SkillManager(
            skills_dirs=[str(tmpdir)],
            active_skill_names=["tool-skill"],
        )
        use_skill_tool = manager.create_use_skill_tool()

        assert use_skill_tool is not None
        assert use_skill_tool.definition.name == "use_skill"
        assert "tool-skill" in use_skill_tool.definition.description


def test_skill_manager_get_tools_returns_use_skill_tool():
    """get_tools() must return the use_skill NativeTool when active skills exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        _create_test_skill(tmpdir, "my-skill", "My description", "# Instructions\n\nDo something.")

        manager = SkillManager(
            skills_dirs=[str(tmpdir)],
            active_skill_names=["my-skill"],
        )
        tools = manager.get_tools()

        assert len(tools) == 1
        assert tools[0].definition.name == "use_skill"


def test_skill_manager_get_tools_empty_when_no_active_skills():
    """get_tools() must return [] when no skills are active."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        _create_test_skill(tmpdir, "unused", "Unused", "Body")

        manager = SkillManager(skills_dirs=[str(tmpdir)], active_skill_names=[])
        assert manager.get_tools() == []

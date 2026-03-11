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

        names = [t.definition.name for t in tools]
        assert "use_skill" in names


def test_skill_manager_get_tools_empty_when_no_active_skills():
    """get_tools() must return [] when no skills are active."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        _create_test_skill(tmpdir, "unused", "Unused", "Body")

        manager = SkillManager(skills_dirs=[str(tmpdir)], active_skill_names=[])
        assert manager.get_tools() == []


def test_activate_skill_shows_relative_resource_paths():
    """activate_skill() must list resource files as relative paths, not absolute."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        skill_dir = tmpdir / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: my-skill\ndescription: A skill\n---\n\n# Instructions"
        )
        scripts_dir = skill_dir / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "run.py").write_text("print('hello')")

        manager = SkillManager(
            skills_dirs=[str(tmpdir)],
            active_skill_names=["my-skill"],
        )

        result = asyncio.run(manager.activate_skill("my-skill"))
        # Must contain relative path, not absolute
        assert "scripts/run.py" in result
        assert str(tmpdir) not in result


def test_read_skill_resource_list_files():
    """read_skill_resource with empty file_path returns file listing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        skill_dir = tmpdir / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: my-skill\ndescription: A skill\n---\n\n# Body"
        )
        scripts_dir = skill_dir / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "run.py").write_text("print(1)")
        (skill_dir / "notes.txt").write_text("hello")

        manager = SkillManager(
            skills_dirs=[str(tmpdir)],
            active_skill_names=["my-skill"],
        )
        tool = manager.create_read_skill_resource_tool()
        assert tool is not None

        result = asyncio.run(tool.execute({"skill_name": "my-skill", "file_path": ""}))
        assert "scripts/run.py" in result
        assert "notes.txt" in result
        # SKILL.md should not appear in listing
        assert "SKILL.md" not in result


def test_read_skill_resource_read_file():
    """read_skill_resource with a valid file_path returns file content."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        skill_dir = tmpdir / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: my-skill\ndescription: A skill\n---\n\n# Body"
        )
        scripts_dir = skill_dir / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "run.py").write_text("print('hello world')")

        manager = SkillManager(
            skills_dirs=[str(tmpdir)],
            active_skill_names=["my-skill"],
        )
        tool = manager.create_read_skill_resource_tool()

        result = asyncio.run(tool.execute({"skill_name": "my-skill", "file_path": "scripts/run.py"}))
        assert "print('hello world')" in result


def test_read_skill_resource_nonexistent_file():
    """read_skill_resource returns error for nonexistent file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        _create_test_skill(tmpdir, "my-skill", "A skill", "Body")

        manager = SkillManager(
            skills_dirs=[str(tmpdir)],
            active_skill_names=["my-skill"],
        )
        tool = manager.create_read_skill_resource_tool()

        result = asyncio.run(tool.execute({"skill_name": "my-skill", "file_path": "no-such-file.txt"}))
        assert "Error" in result
        assert "not found" in result


def test_read_skill_resource_path_traversal():
    """read_skill_resource rejects path traversal attempts."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        _create_test_skill(tmpdir, "my-skill", "A skill", "Body")
        # Create a file outside skill dir
        (tmpdir / "secret.txt").write_text("secret data")

        manager = SkillManager(
            skills_dirs=[str(tmpdir)],
            active_skill_names=["my-skill"],
        )
        tool = manager.create_read_skill_resource_tool()

        result = asyncio.run(tool.execute({"skill_name": "my-skill", "file_path": "../secret.txt"}))
        assert "Error" in result
        assert "secret data" not in result


def test_read_skill_resource_inactive_skill():
    """read_skill_resource rejects requests for non-active skills."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        _create_test_skill(tmpdir, "other-skill", "Other", "Body")

        manager = SkillManager(
            skills_dirs=[str(tmpdir)],
            active_skill_names=[],
        )
        # No active skills -> no tool
        tool = manager.create_read_skill_resource_tool()
        assert tool is None


def test_get_tools_includes_read_skill_resource():
    """get_tools() returns both use_skill and read_skill_resource."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        _create_test_skill(tmpdir, "my-skill", "My desc", "Body")

        manager = SkillManager(
            skills_dirs=[str(tmpdir)],
            active_skill_names=["my-skill"],
        )
        tools = manager.get_tools()
        names = [t.definition.name for t in tools]
        assert "use_skill" in names
        assert "read_skill_resource" in names


def test_update_skill_tool_write_file():
    """update_skill with action=write creates/overwrites a file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        _create_test_skill(tmpdir, "my-skill", "A skill", "Body")

        manager = SkillManager(skills_dirs=[str(tmpdir)], active_skill_names=["my-skill"])
        tool = manager.create_update_skill_tool()
        assert tool is not None

        result = asyncio.run(tool.execute({
            "skill_name": "my-skill",
            "action": "write",
            "file_path": "scripts/run.py",
            "content": "print('new')",
        }))
        assert "Error" not in result
        assert (tmpdir / "my-skill" / "scripts" / "run.py").read_text() == "print('new')"


def test_update_skill_tool_write_skill_md():
    """update_skill with action=write can overwrite SKILL.md."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        _create_test_skill(tmpdir, "my-skill", "A skill", "Old body")

        manager = SkillManager(skills_dirs=[str(tmpdir)], active_skill_names=["my-skill"])
        tool = manager.create_update_skill_tool()

        new_content = "---\nname: my-skill\ndescription: Updated\n---\n\n# New body"
        result = asyncio.run(tool.execute({
            "skill_name": "my-skill",
            "action": "write",
            "file_path": "SKILL.md",
            "content": new_content,
        }))
        assert "Error" not in result
        assert "New body" in (tmpdir / "my-skill" / "SKILL.md").read_text()


def test_update_skill_tool_delete_file():
    """update_skill with action=delete removes a file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        skill_dir = tmpdir / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: my-skill\ndescription: A skill\n---\n\nBody"
        )
        (skill_dir / "extra.txt").write_text("delete me")

        manager = SkillManager(skills_dirs=[str(tmpdir)], active_skill_names=["my-skill"])
        tool = manager.create_update_skill_tool()

        result = asyncio.run(tool.execute({
            "skill_name": "my-skill",
            "action": "delete",
            "file_path": "extra.txt",
        }))
        assert "Error" not in result
        assert not (skill_dir / "extra.txt").exists()


def test_update_skill_tool_delete_skill_md_refused():
    """update_skill refuses to delete SKILL.md."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        _create_test_skill(tmpdir, "my-skill", "A skill", "Body")

        manager = SkillManager(skills_dirs=[str(tmpdir)], active_skill_names=["my-skill"])
        tool = manager.create_update_skill_tool()

        result = asyncio.run(tool.execute({
            "skill_name": "my-skill",
            "action": "delete",
            "file_path": "SKILL.md",
        }))
        assert "Error" in result
        assert (tmpdir / "my-skill" / "SKILL.md").exists()


def test_update_skill_tool_path_traversal():
    """update_skill rejects path traversal."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        _create_test_skill(tmpdir, "my-skill", "A skill", "Body")

        manager = SkillManager(skills_dirs=[str(tmpdir)], active_skill_names=["my-skill"])
        tool = manager.create_update_skill_tool()

        result = asyncio.run(tool.execute({
            "skill_name": "my-skill",
            "action": "write",
            "file_path": "../evil.txt",
            "content": "hacked",
        }))
        assert "Error" in result
        assert not (tmpdir / "evil.txt").exists()


def test_update_skill_tool_invalid_action():
    """update_skill rejects unknown actions."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        _create_test_skill(tmpdir, "my-skill", "A skill", "Body")

        manager = SkillManager(skills_dirs=[str(tmpdir)], active_skill_names=["my-skill"])
        tool = manager.create_update_skill_tool()

        result = asyncio.run(tool.execute({
            "skill_name": "my-skill",
            "action": "rename",
            "file_path": "x.txt",
        }))
        assert "Error" in result


def test_update_skill_tool_unknown_skill():
    """update_skill returns error for nonexistent skill."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        _create_test_skill(tmpdir, "existing-skill", "Exists", "Body")

        manager = SkillManager(skills_dirs=[str(tmpdir)], active_skill_names=["existing-skill"])
        tool = manager.create_update_skill_tool()

        result = asyncio.run(tool.execute({
            "skill_name": "no-such-skill",
            "action": "write",
            "file_path": "test.txt",
            "content": "data",
        }))
        assert "Error" in result

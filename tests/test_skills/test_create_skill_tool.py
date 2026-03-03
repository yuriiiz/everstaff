import pytest


@pytest.mark.asyncio
async def test_create_skill_writes_to_all_install_dirs(tmp_path):
    """create_skill writes SKILL.md to every install_dir."""
    from everstaff.skills.create_skill_tool import CreateSkillTool

    dir_a = tmp_path / "skills_a"
    dir_b = tmp_path / "skills_b"
    dir_a.mkdir()
    dir_b.mkdir()

    tool = CreateSkillTool(install_dirs=[str(dir_a), str(dir_b)])
    result = await tool.execute({
        "skill_name": "my-test-skill",
        "description": "Use when testing skill creation",
        "content": "# My Test Skill\n\nDo the thing.",
    })

    assert result.is_error is False
    assert "my-test-skill" in result.content

    for d in [dir_a, dir_b]:
        skill_md = d / "my-test-skill" / "SKILL.md"
        assert skill_md.exists(), f"SKILL.md missing in {d}"
        text = skill_md.read_text()
        assert "name: my-test-skill" in text
        assert "Use when testing skill creation" in text
        assert "# My Test Skill" in text


@pytest.mark.asyncio
async def test_create_skill_with_scripts(tmp_path):
    """create_skill writes optional script files."""
    from everstaff.skills.create_skill_tool import CreateSkillTool

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()

    tool = CreateSkillTool(install_dirs=[str(skills_dir)])
    result = await tool.execute({
        "skill_name": "scripted-skill",
        "description": "Use when scripts needed",
        "content": "# Scripted\n\nHas scripts.",
        "scripts": '{"run.py": "print(1)", "helper.sh": "echo hi"}',
    })

    assert result.is_error is False
    assert (skills_dir / "scripted-skill" / "scripts" / "run.py").read_text() == "print(1)"
    assert (skills_dir / "scripted-skill" / "scripts" / "helper.sh").read_text() == "echo hi"


@pytest.mark.asyncio
async def test_create_skill_skips_readonly_dirs(tmp_path):
    """create_skill silently skips dirs that raise PermissionError."""
    from everstaff.skills.create_skill_tool import CreateSkillTool

    writable = tmp_path / "writable"
    writable.mkdir()
    readonly = tmp_path / "readonly"
    readonly.mkdir()
    readonly.chmod(0o444)

    tool = CreateSkillTool(install_dirs=[str(writable), str(readonly)])
    result = await tool.execute({
        "skill_name": "perm-test",
        "description": "Use when testing",
        "content": "# Test",
    })

    assert result.is_error is False
    assert (writable / "perm-test" / "SKILL.md").exists()

    # Cleanup: restore permissions so tmp_path can be deleted
    readonly.chmod(0o755)


@pytest.mark.asyncio
async def test_create_skill_rejects_existing_skill(tmp_path):
    """create_skill returns error if skill already exists in any install dir."""
    from everstaff.skills.create_skill_tool import CreateSkillTool

    skills_dir = tmp_path / "skills"
    (skills_dir / "existing-skill").mkdir(parents=True)

    tool = CreateSkillTool(install_dirs=[str(skills_dir)])
    result = await tool.execute({
        "skill_name": "existing-skill",
        "description": "Use when ...",
        "content": "# Existing",
    })

    assert result.is_error is True
    assert "already exists" in result.content


@pytest.mark.asyncio
async def test_bootstrap_registers_create_skill_tool():
    """enable_bootstrap=True registers both create_agent and create_skill."""
    from unittest.mock import MagicMock, AsyncMock
    from everstaff.builder.agent_builder import AgentBuilder
    from everstaff.schema.agent_spec import AgentSpec

    spec = AgentSpec(agent_name="test", enable_bootstrap=True, tools=["Bash"])
    env = MagicMock()
    env.config.skills_dirs = ["./skills"]
    env.config.tools_dirs = ["./tools"]
    env.config.permissions.deny = []
    env.build_llm_client = MagicMock()
    env.build_memory_store = AsyncMock(return_value=MagicMock(load=AsyncMock(return_value=[])))
    env.build_tracer = MagicMock()
    env.sessions_dir = MagicMock(return_value=None)
    env.build_file_store = MagicMock(side_effect=NotImplementedError)

    builder = AgentBuilder(spec, env, session_id="test-sess")
    runtime, ctx = await builder.build()

    tool_names = list(ctx.tool_registry._tools.keys())
    assert "create_agent" in tool_names
    assert "create_skill" in tool_names

import pytest


@pytest.mark.asyncio
async def test_framework_tool_registered_for_builtin_agent():
    """system_reconcile is registered when source=builtin."""
    from everstaff.builder.agent_builder import AgentBuilder
    from everstaff.builder.environment import TestEnvironment
    from everstaff.schema.agent_spec import AgentSpec

    spec = AgentSpec(agent_name="reconciler", source="builtin", tools=["system_reconcile"])
    env = TestEnvironment()
    builder = AgentBuilder(spec, env, session_id="test-fw")
    runtime, ctx = await builder.build()

    tool_names = list(ctx.tool_registry._tools.keys())
    assert "system_reconcile" in tool_names


@pytest.mark.asyncio
async def test_framework_tool_rejected_for_custom_agent():
    """system_reconcile is NOT registered when source=custom."""
    from everstaff.builder.agent_builder import AgentBuilder
    from everstaff.builder.environment import TestEnvironment
    from everstaff.schema.agent_spec import AgentSpec

    spec = AgentSpec(agent_name="user-agent", source="custom", tools=["system_reconcile"])
    env = TestEnvironment()
    builder = AgentBuilder(spec, env, session_id="test-fw-reject")
    runtime, ctx = await builder.build()

    tool_names = list(ctx.tool_registry._tools.keys())
    assert "system_reconcile" not in tool_names


@pytest.mark.asyncio
async def test_framework_and_regular_tools_coexist():
    """Both framework and regular tools work together."""
    from everstaff.builder.agent_builder import AgentBuilder
    from everstaff.builder.environment import TestEnvironment
    from everstaff.schema.agent_spec import AgentSpec

    spec = AgentSpec(agent_name="mixed", source="builtin", tools=["Bash", "system_reconcile"])
    env = TestEnvironment()
    builder = AgentBuilder(spec, env, session_id="test-fw-mixed")
    runtime, ctx = await builder.build()

    tool_names = list(ctx.tool_registry._tools.keys())
    assert "system_reconcile" in tool_names
    # Bash may or may not load depending on tools_dirs, but system_reconcile must be present


@pytest.mark.asyncio
async def test_update_skill_auto_registered_with_skills(tmp_path):
    """update_skill is auto-registered when agent has active skills."""
    from everstaff.builder.agent_builder import AgentBuilder
    from everstaff.builder.environment import TestEnvironment
    from everstaff.core.config import FrameworkConfig
    from everstaff.schema.agent_spec import AgentSpec
    from everstaff.schema.model_config import ModelMapping

    skills_dir = tmp_path / "skills"
    skill_dir = skills_dir / "test-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: test-skill\ndescription: Test\n---\n\nBody"
    )

    config = FrameworkConfig(
        model_mappings={"smart": ModelMapping(model_id="test-model")},
        skills_dirs=[str(skills_dir)],
    )
    spec = AgentSpec(agent_name="test", skills=["test-skill"])
    env = TestEnvironment(config=config)

    builder = AgentBuilder(spec, env, session_id="test-update-skill-auto")
    runtime, ctx = await builder.build()

    tool_names = list(ctx.tool_registry._tools.keys())
    assert "update_skill" in tool_names
    assert "use_skill" in tool_names
    assert "read_skill_resource" in tool_names

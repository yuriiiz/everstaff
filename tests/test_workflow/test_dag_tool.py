import pytest
from unittest.mock import MagicMock


@pytest.mark.asyncio
async def test_agent_builder_registers_new_workflow_tools():
    """AgentBuilder registers write_plan and execute_plan_step when spec.workflow is set."""
    from everstaff.builder.agent_builder import AgentBuilder
    from everstaff.builder.environment import TestEnvironment
    from everstaff.schema.agent_spec import AgentSpec

    spec = AgentSpec(
        agent_name="coordinator",
        instructions="coordinate",
        workflow={"max_parallel": 3},
    )
    env = TestEnvironment()
    _, ctx = await AgentBuilder(spec, env).build()

    tool_names = [t.name for t in ctx.tool_registry.get_definitions()]
    assert "write_plan" in tool_names
    assert "execute_plan_step" in tool_names
    assert "write_workflow_plan" not in tool_names


@pytest.mark.asyncio
async def test_agent_builder_no_workflow_tools_without_config():
    from everstaff.builder.agent_builder import AgentBuilder
    from everstaff.builder.environment import TestEnvironment
    from everstaff.schema.agent_spec import AgentSpec

    spec = AgentSpec(agent_name="simple", instructions="do stuff")
    env = TestEnvironment()
    _, ctx = await AgentBuilder(spec, env).build()

    tool_names = [t.name for t in ctx.tool_registry.get_definitions()]
    assert "write_plan" not in tool_names
    assert "execute_plan_step" not in tool_names

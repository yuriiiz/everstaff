"""AgentBuilder must accept session_id to reuse an existing session."""
import pytest
from everstaff.builder.agent_builder import AgentBuilder
from everstaff.builder.environment import TestEnvironment
from everstaff.schema.agent_spec import AgentSpec


@pytest.mark.asyncio
async def test_builder_uses_provided_session_id():
    """When session_id is passed, build() must use it instead of generating a new one."""
    spec = AgentSpec(agent_name="test-agent")
    env = TestEnvironment()
    builder = AgentBuilder(spec, env, session_id="existing-session-123")
    runtime, ctx = await builder.build()
    assert ctx.session_id == "existing-session-123"


@pytest.mark.asyncio
async def test_builder_generates_session_id_when_none():
    """When session_id is None, build() generates a new UUID as before."""
    spec = AgentSpec(agent_name="test-agent")
    env = TestEnvironment()
    builder = AgentBuilder(spec, env)
    runtime, ctx = await builder.build()
    assert ctx.session_id  # non-empty
    assert ctx.session_id != "existing-session-123"

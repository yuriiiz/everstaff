import pytest
import yaml
from unittest.mock import AsyncMock
from pathlib import Path


@pytest.mark.asyncio
async def test_create_agent_creates_yaml_and_returns_name(tmp_path):
    """create_agent writes YAML and returns the agent name."""
    from everstaff.tools.bootstrap import CreateAgentTool
    from everstaff.core.context import AgentContext
    from everstaff.nulls import NullTracer, AllowAllChecker
    from everstaff.tools.pipeline import ToolCallPipeline
    from everstaff.tools.stages import ExecutionStage, PermissionStage
    from everstaff.tools.default_registry import DefaultToolRegistry
    from everstaff.agents.sub_agent_provider import DefaultSubAgentProvider
    from everstaff.protocols import LLMResponse

    registry = DefaultToolRegistry()
    pipeline = ToolCallPipeline([PermissionStage(AllowAllChecker()), ExecutionStage(registry)])
    memory = AsyncMock()
    memory.load = AsyncMock(return_value=[])
    memory.save = AsyncMock()

    from unittest.mock import MagicMock
    provider = DefaultSubAgentProvider([], env=MagicMock())
    ctx = AgentContext(
        tool_registry=registry,
        memory=memory,
        tool_pipeline=pipeline,
        agent_name="coordinator",
        session_id="sess-bootstrap",
        tracer=NullTracer(),
        sessions_dir=str(tmp_path),
    )
    ctx.sub_agent_provider = provider

    mock_yaml = yaml.dump({
        "name": "sql_expert",
        "description": "SQL query optimization expert",
        "instructions": "You are an expert in SQL optimization.",
        "adviced_model_kind": "smart",
        "tools": [],
        "skills": [],
    })

    llm = AsyncMock()
    llm.complete = AsyncMock(return_value=LLMResponse(content=mock_yaml, tool_calls=[]))

    tool = CreateAgentTool(ctx=ctx, llm=llm)
    result = await tool.execute({"name": "sql_expert", "domain": "SQL query optimization"})

    assert result.is_error is False
    assert result.content == "sql_expert"

    yaml_path = tmp_path / "sess-bootstrap" / "agents" / "sql_expert.yaml"
    assert yaml_path.exists()


@pytest.mark.asyncio
async def test_create_agent_uses_cache_on_second_call(tmp_path):
    """Second call with same name returns immediately without LLM call."""
    from everstaff.tools.bootstrap import CreateAgentTool
    from everstaff.core.context import AgentContext
    from everstaff.nulls import NullTracer, AllowAllChecker
    from everstaff.tools.pipeline import ToolCallPipeline
    from everstaff.tools.stages import ExecutionStage, PermissionStage
    from everstaff.tools.default_registry import DefaultToolRegistry
    from everstaff.agents.sub_agent_provider import DefaultSubAgentProvider

    from unittest.mock import MagicMock
    registry = DefaultToolRegistry()
    pipeline = ToolCallPipeline([PermissionStage(AllowAllChecker()), ExecutionStage(registry)])
    memory = AsyncMock()
    provider = DefaultSubAgentProvider([], env=MagicMock())
    ctx = AgentContext(
        tool_registry=registry, memory=memory, tool_pipeline=pipeline,
        agent_name="coordinator", session_id="sess-cache",
        tracer=NullTracer(), sessions_dir=str(tmp_path),
    )
    ctx.sub_agent_provider = provider

    # Pre-create the YAML file (simulate cache hit)
    agent_dir = tmp_path / "sess-cache" / "agents"
    agent_dir.mkdir(parents=True)
    (agent_dir / "sql_expert.yaml").write_text("name: sql_expert\ndescription: cached\n")

    llm = AsyncMock()
    llm.complete = AsyncMock()

    tool = CreateAgentTool(ctx=ctx, llm=llm)
    result = await tool.execute({"name": "sql_expert", "domain": "SQL"})
    assert result.content == "sql_expert"
    llm.complete.assert_not_called()


@pytest.mark.asyncio
async def test_create_agent_registers_into_provider(tmp_path):
    """After successful generation, the agent is registered in the SubAgentProvider."""
    from unittest.mock import AsyncMock, MagicMock
    from everstaff.tools.bootstrap import CreateAgentTool
    from everstaff.core.context import AgentContext
    from everstaff.nulls import NullTracer, AllowAllChecker
    from everstaff.tools.pipeline import ToolCallPipeline
    from everstaff.tools.stages import ExecutionStage, PermissionStage
    from everstaff.tools.default_registry import DefaultToolRegistry
    from everstaff.agents.sub_agent_provider import DefaultSubAgentProvider
    from everstaff.protocols import LLMResponse
    from everstaff.builder.environment import CLIEnvironment

    registry = DefaultToolRegistry()
    pipeline = ToolCallPipeline([PermissionStage(AllowAllChecker()), ExecutionStage(registry)])
    memory = AsyncMock()
    memory.load = AsyncMock(return_value=[])
    memory.save = AsyncMock()
    from everstaff.core.config import FrameworkConfig
    env = CLIEnvironment(sessions_dir=str(tmp_path), config=FrameworkConfig(tracers=[]))
    provider = DefaultSubAgentProvider([], env=env)

    ctx = AgentContext(
        tool_registry=registry,
        memory=memory,
        tool_pipeline=pipeline,
        agent_name="coordinator",
        session_id="sess-reg",
        tracer=NullTracer(),
        sessions_dir=str(tmp_path),
    )
    ctx.sub_agent_provider = provider

    # Provide a real-ish environment so _register_agent can register the sub-agent
    ctx._env = env

    mock_yaml = yaml.dump({
        "name": "data_expert",
        "description": "Data analysis expert",
        "instructions": "You analyze data.",
        "adviced_model_kind": "smart",
        "tools": [],
        "skills": [],
    })

    llm = AsyncMock()
    llm.complete = AsyncMock(return_value=LLMResponse(content=mock_yaml, tool_calls=[]))

    tool = CreateAgentTool(ctx=ctx, llm=llm)
    result = await tool.execute({"name": "data_expert", "domain": "data analysis"})

    assert result.is_error is False
    assert result.content == "data_expert"
    # Provider should now have the new agent registered in the DelegateTaskTool registry
    assert provider._tool is not None
    assert "data_expert" in provider._tool._registry


@pytest.mark.asyncio
async def test_create_agent_persist_writes_to_agents_dir(tmp_path):
    """persist=True writes agent YAML to agents_dir with source: custom."""
    from everstaff.tools.bootstrap import CreateAgentTool
    from everstaff.core.context import AgentContext
    from everstaff.nulls import NullTracer, AllowAllChecker
    from everstaff.tools.pipeline import ToolCallPipeline
    from everstaff.tools.stages import ExecutionStage, PermissionStage
    from everstaff.tools.default_registry import DefaultToolRegistry
    from everstaff.agents.sub_agent_provider import DefaultSubAgentProvider
    from everstaff.protocols import LLMResponse
    from everstaff.builder.environment import CLIEnvironment
    from everstaff.core.config import FrameworkConfig

    agents_dir = tmp_path / "agents"
    sessions_dir = tmp_path / "sessions"

    config = FrameworkConfig(tracers=[], agents_dir=str(agents_dir))
    env = CLIEnvironment(sessions_dir=str(sessions_dir), config=config)

    registry = DefaultToolRegistry()
    pipeline = ToolCallPipeline([PermissionStage(AllowAllChecker()), ExecutionStage(registry)])
    memory = AsyncMock()
    memory.load = AsyncMock(return_value=[])
    memory.save = AsyncMock()
    provider = DefaultSubAgentProvider([], env=env)

    ctx = AgentContext(
        tool_registry=registry, memory=memory, tool_pipeline=pipeline,
        agent_name="coordinator", session_id="sess-persist",
        tracer=NullTracer(), sessions_dir=str(sessions_dir),
        sub_agent_provider=provider,
    )
    ctx._env = env

    mock_yaml = yaml.dump({
        "name": "sql_expert",
        "description": "SQL optimization expert",
        "instructions": "You optimize SQL.",
        "adviced_model_kind": "smart",
        "tools": [],
        "skills": [],
    })

    llm = AsyncMock()
    llm.complete = AsyncMock(return_value=LLMResponse(content=mock_yaml, tool_calls=[]))

    tool = CreateAgentTool(ctx=ctx, llm=llm)
    result = await tool.execute({"name": "sql_expert", "domain": "SQL", "persist": True})

    assert result.is_error is False
    assert result.content == "sql_expert"

    # Check persistent file exists with correct fields
    persistent_path = agents_dir / "sql_expert.yaml"
    assert persistent_path.exists()
    data = yaml.safe_load(persistent_path.read_text())
    assert data["agent_name"] == "sql_expert"
    assert data["source"] == "custom"


@pytest.mark.asyncio
async def test_create_agent_persist_conflict_returns_error(tmp_path):
    """persist=True with existing agent in agents_dir returns error."""
    from everstaff.tools.bootstrap import CreateAgentTool
    from everstaff.core.context import AgentContext
    from everstaff.nulls import NullTracer, AllowAllChecker
    from everstaff.tools.pipeline import ToolCallPipeline
    from everstaff.tools.stages import ExecutionStage, PermissionStage
    from everstaff.tools.default_registry import DefaultToolRegistry
    from everstaff.agents.sub_agent_provider import DefaultSubAgentProvider
    from everstaff.builder.environment import CLIEnvironment
    from everstaff.core.config import FrameworkConfig

    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    (agents_dir / "sql_expert.yaml").write_text("agent_name: sql_expert\n")

    sessions_dir = tmp_path / "sessions"
    config = FrameworkConfig(tracers=[], agents_dir=str(agents_dir))
    env = CLIEnvironment(sessions_dir=str(sessions_dir), config=config)

    registry = DefaultToolRegistry()
    pipeline = ToolCallPipeline([PermissionStage(AllowAllChecker()), ExecutionStage(registry)])
    memory = AsyncMock()
    provider = DefaultSubAgentProvider([], env=env)

    ctx = AgentContext(
        tool_registry=registry, memory=memory, tool_pipeline=pipeline,
        agent_name="coordinator", session_id="sess-conflict",
        tracer=NullTracer(), sessions_dir=str(sessions_dir),
        sub_agent_provider=provider,
    )
    ctx._env = env

    llm = AsyncMock()
    tool = CreateAgentTool(ctx=ctx, llm=llm)
    result = await tool.execute({"name": "sql_expert", "domain": "SQL", "persist": True})

    assert result.is_error is True
    assert "already exists" in result.content
    llm.complete.assert_not_called()


@pytest.mark.asyncio
async def test_create_agent_no_persist_does_not_write_agents_dir(tmp_path):
    """persist=False (default) should not create anything in agents_dir."""
    from everstaff.tools.bootstrap import CreateAgentTool
    from everstaff.core.context import AgentContext
    from everstaff.nulls import NullTracer, AllowAllChecker
    from everstaff.tools.pipeline import ToolCallPipeline
    from everstaff.tools.stages import ExecutionStage, PermissionStage
    from everstaff.tools.default_registry import DefaultToolRegistry
    from everstaff.agents.sub_agent_provider import DefaultSubAgentProvider
    from everstaff.protocols import LLMResponse
    from everstaff.builder.environment import CLIEnvironment
    from everstaff.core.config import FrameworkConfig

    agents_dir = tmp_path / "agents"
    sessions_dir = tmp_path / "sessions"

    config = FrameworkConfig(tracers=[], agents_dir=str(agents_dir))
    env = CLIEnvironment(sessions_dir=str(sessions_dir), config=config)

    registry = DefaultToolRegistry()
    pipeline = ToolCallPipeline([PermissionStage(AllowAllChecker()), ExecutionStage(registry)])
    memory = AsyncMock()
    memory.load = AsyncMock(return_value=[])
    memory.save = AsyncMock()
    provider = DefaultSubAgentProvider([], env=env)

    ctx = AgentContext(
        tool_registry=registry, memory=memory, tool_pipeline=pipeline,
        agent_name="coordinator", session_id="sess-nopersist",
        tracer=NullTracer(), sessions_dir=str(sessions_dir),
        sub_agent_provider=provider,
    )
    ctx._env = env

    mock_yaml = yaml.dump({
        "name": "temp_agent",
        "description": "Temporary agent",
        "instructions": "Temporary.",
        "adviced_model_kind": "smart",
        "tools": [],
        "skills": [],
    })

    llm = AsyncMock()
    llm.complete = AsyncMock(return_value=LLMResponse(content=mock_yaml, tool_calls=[]))

    tool = CreateAgentTool(ctx=ctx, llm=llm)
    result = await tool.execute({"name": "temp_agent", "domain": "temp"})

    assert result.is_error is False
    # agents_dir should not even be created
    assert not agents_dir.exists()

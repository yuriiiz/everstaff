# tests/test_agents/test_delegate_task_tool.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from everstaff.schema.agent_spec import SubAgentSpec
from everstaff.builder.environment import TestEnvironment
from everstaff.agents.delegate_task_tool import DelegateTaskTool


def make_spec(name: str) -> SubAgentSpec:
    return SubAgentSpec(name=name, description=f"{name} agent", instructions="")


def test_definition_has_single_tool_name():
    tool = DelegateTaskTool(
        specs=[make_spec("researcher"), make_spec("coder")],
        env=TestEnvironment(),
    )
    assert tool.definition.name == "delegate_task_to_subagent"


def test_definition_enum_contains_all_agent_names():
    tool = DelegateTaskTool(
        specs=[make_spec("researcher"), make_spec("coder")],
        env=TestEnvironment(),
    )
    enum = tool.definition.parameters["properties"]["agent_name"]["enum"]
    assert set(enum) == {"researcher", "coder"}


def test_definition_enum_updates_after_register():
    tool = DelegateTaskTool(specs=[make_spec("researcher")], env=TestEnvironment())
    tool.register("coder", make_spec("coder"))
    enum = tool.definition.parameters["properties"]["agent_name"]["enum"]
    assert "coder" in enum


@pytest.mark.asyncio
async def test_execute_routes_to_correct_agent():
    tool = DelegateTaskTool(
        specs=[make_spec("researcher"), make_spec("coder")],
        env=TestEnvironment(),
    )
    mock_runtime = MagicMock()
    mock_runtime.run = AsyncMock(return_value="research done")
    mock_runtime.stats = None
    mock_ctx = MagicMock()

    with patch("everstaff.agents.delegate_task_tool.AgentBuilder") as MockBuilder:
        mock_builder_instance = MagicMock()
        mock_builder_instance.build = AsyncMock(return_value=(mock_runtime, mock_ctx))
        MockBuilder.return_value = mock_builder_instance

        result = await tool.execute({"agent_name": "researcher", "prompt": "find stuff"})

    assert result.content == "research done"
    assert not result.is_error
    # Verify AgentBuilder was called with the researcher spec
    built_spec = MockBuilder.call_args[0][0]
    assert built_spec.agent_name == "researcher"


@pytest.mark.asyncio
async def test_execute_unknown_agent_returns_error():
    tool = DelegateTaskTool(specs=[make_spec("researcher")], env=TestEnvironment())
    result = await tool.execute({"agent_name": "nonexistent", "prompt": "hello"})
    assert result.is_error
    assert "nonexistent" in result.content


@pytest.mark.asyncio
async def test_execute_forwards_child_stats():
    from everstaff.schema.token_stats import SessionStats, TokenUsage
    tool = DelegateTaskTool(specs=[make_spec("helper")], env=TestEnvironment())
    child_stats = SessionStats()
    child_stats.record(TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15, model_id="gpt-4"))

    mock_runtime = MagicMock()
    mock_runtime.run = AsyncMock(return_value="done")
    mock_runtime.stats = child_stats
    mock_ctx = MagicMock()

    with patch("everstaff.agents.delegate_task_tool.AgentBuilder") as MockBuilder:
        mock_builder_instance = MagicMock()
        mock_builder_instance.build = AsyncMock(return_value=(mock_runtime, mock_ctx))
        MockBuilder.return_value = mock_builder_instance
        result = await tool.execute({"agent_name": "helper", "prompt": "task"})

    assert result.child_stats is not None
    assert result.child_stats.own_calls[0].input_tokens == 10


# --- Provider tests ---

def test_provider_get_tools_returns_single_tool():
    from everstaff.agents.sub_agent_provider import DefaultSubAgentProvider
    provider = DefaultSubAgentProvider(
        specs=[make_spec("researcher"), make_spec("coder")],
        env=TestEnvironment(),
    )
    tools = provider.get_tools()
    assert len(tools) == 1
    assert tools[0].definition.name == "delegate_task_to_subagent"


def test_provider_register_adds_to_enum():
    from everstaff.agents.sub_agent_provider import DefaultSubAgentProvider
    provider = DefaultSubAgentProvider(specs=[make_spec("researcher")], env=TestEnvironment())
    provider.register("coder", make_spec("coder"))
    enum = provider.get_tools()[0].definition.parameters["properties"]["agent_name"]["enum"]
    assert "coder" in enum


def test_provider_prompt_injection_lists_all_agents():
    from everstaff.agents.sub_agent_provider import DefaultSubAgentProvider
    provider = DefaultSubAgentProvider(
        specs=[make_spec("researcher"), make_spec("coder")],
        env=TestEnvironment(),
    )
    prompt = provider.get_prompt_injection()
    assert "researcher" in prompt
    assert "coder" in prompt
    assert "delegate_task_to_subagent" in prompt


def test_provider_prompt_injection_includes_behavioral_rules():
    from everstaff.agents.sub_agent_provider import DefaultSubAgentProvider
    provider = DefaultSubAgentProvider(
        specs=[make_spec("researcher")],
        env=TestEnvironment(),
    )
    prompt = provider.get_prompt_injection()
    assert "MUST" in prompt
    assert "NEVER" in prompt
    assert "delegate_task_to_subagent" in prompt


def test_provider_empty_returns_no_tools_no_prompt():
    from everstaff.agents.sub_agent_provider import DefaultSubAgentProvider
    provider = DefaultSubAgentProvider(specs=[], env=TestEnvironment())
    assert provider.get_tools() == []
    assert provider.get_prompt_injection() == ""


# --- HITL intercept + resume tests ---

@pytest.mark.asyncio
async def test_execute_catches_child_hitl_and_returns_structured_info():
    """When child runtime raises HumanApprovalRequired, DelegateTaskTool should
    catch it and return structured HITL info as a normal tool result."""
    from everstaff.protocols import HumanApprovalRequired, HitlRequest

    tool = DelegateTaskTool(specs=[make_spec("helper")], env=TestEnvironment())

    hitl_request = HitlRequest(
        hitl_id="hitl-child-001",
        type="approve_reject",
        prompt="Deploy to production?",
        options=["yes", "no"],
        context="staging passed",
    )

    mock_runtime = MagicMock()
    mock_runtime.run = AsyncMock(side_effect=HumanApprovalRequired(hitl_request))
    mock_runtime.stats = None
    mock_ctx = MagicMock()
    mock_ctx.session_id = "child-session-123"
    mock_ctx.memory = AsyncMock()
    mock_ctx.aclose = AsyncMock()

    with patch("everstaff.agents.delegate_task_tool.AgentBuilder") as MockBuilder:
        mock_builder_instance = MagicMock()
        mock_builder_instance.build = AsyncMock(return_value=(mock_runtime, mock_ctx))
        MockBuilder.return_value = mock_builder_instance

        result = await tool.execute({"agent_name": "helper", "prompt": "deploy now"})

    assert not result.is_error
    assert "[SUB_AGENT_HITL]" in result.content
    assert "helper" in result.content
    assert "Deploy to production?" in result.content
    assert "hitl-child-001" in result.content
    assert "child-session-123" in result.content


@pytest.mark.asyncio
async def test_execute_resumes_child_session_with_hitl_response():
    """When resume_session_id and hitl_response are provided, DelegateTaskTool
    should resolve the child's HITL and resume the child session."""

    tool = DelegateTaskTool(specs=[make_spec("helper")], env=TestEnvironment())

    mock_runtime = MagicMock()
    mock_runtime.run = AsyncMock(return_value="deployment complete")
    mock_runtime.stats = None
    mock_ctx = MagicMock()
    mock_ctx.session_id = "child-session-456"
    mock_ctx.memory = MagicMock()
    mock_ctx.memory.load = AsyncMock(return_value=[])
    mock_ctx.memory.save = AsyncMock()
    mock_ctx.aclose = AsyncMock()

    with patch("everstaff.agents.delegate_task_tool.AgentBuilder") as MockBuilder:
        mock_builder_instance = MagicMock()
        mock_builder_instance.build = AsyncMock(return_value=(mock_runtime, mock_ctx))
        MockBuilder.return_value = mock_builder_instance

        with patch.object(tool, "_resolve_child_hitl", new_callable=AsyncMock) as mock_resolve:
            result = await tool.execute({
                "agent_name": "helper",
                "prompt": "continue deployment",
                "resume_session_id": "child-session-456",
                "hitl_response": {"decision": "approved", "comment": "go ahead"},
            })

    assert not result.is_error
    assert result.content == "deployment complete"
    mock_resolve.assert_called_once_with("child-session-456", {"decision": "approved", "comment": "go ahead"})


@pytest.mark.asyncio
async def test_execute_catches_child_hitl_list_and_formats_all():
    """When child raises HumanApprovalRequired with multiple requests,
    DelegateTaskTool must format ALL requests in the tool result."""
    from everstaff.protocols import HumanApprovalRequired, HitlRequest

    tool = DelegateTaskTool(specs=[make_spec("helper")], env=TestEnvironment())

    requests = [
        HitlRequest(hitl_id="h1", type="approve_reject", prompt="Q1?"),
        HitlRequest(hitl_id="h2", type="choose", prompt="Q2?", options=["A", "B"]),
    ]
    mock_runtime = MagicMock()
    mock_runtime.run = AsyncMock(side_effect=HumanApprovalRequired(requests))
    mock_runtime.stats = None
    mock_ctx = MagicMock()
    mock_ctx.session_id = "child-multi"

    with patch("everstaff.agents.delegate_task_tool.AgentBuilder") as MockBuilder:
        mock_builder_instance = MagicMock()
        mock_builder_instance.build = AsyncMock(return_value=(mock_runtime, mock_ctx))
        MockBuilder.return_value = mock_builder_instance
        result = await tool.execute({"agent_name": "helper", "prompt": "do stuff"})

    assert "[SUB_AGENT_HITL]" in result.content
    assert "h1" in result.content
    assert "h2" in result.content
    assert "Q1?" in result.content
    assert "Q2?" in result.content


@pytest.mark.asyncio
async def test_resume_child_catches_new_hitl():
    """When resuming a child that raises another HITL, DelegateTaskTool
    must catch it and return structured info (not crash)."""
    from everstaff.protocols import HumanApprovalRequired, HitlRequest

    tool = DelegateTaskTool(specs=[make_spec("helper")], env=TestEnvironment())

    new_hitl = HitlRequest(hitl_id="h-new", type="provide_input", prompt="More info needed")
    mock_runtime = MagicMock()
    mock_runtime.run = AsyncMock(side_effect=HumanApprovalRequired([new_hitl]))
    mock_runtime.stats = None
    mock_ctx = MagicMock()
    mock_ctx.session_id = "child-resumed"

    with patch("everstaff.agents.delegate_task_tool.AgentBuilder") as MockBuilder:
        mock_builder_instance = MagicMock()
        mock_builder_instance.build = AsyncMock(return_value=(mock_runtime, mock_ctx))
        MockBuilder.return_value = mock_builder_instance

        with patch.object(tool, "_resolve_child_hitl", new_callable=AsyncMock):
            result = await tool.execute({
                "agent_name": "helper",
                "prompt": "continue",
                "resume_session_id": "child-resumed",
                "hitl_response": {"decision": "yes"},
            })

    assert "[SUB_AGENT_HITL]" in result.content
    assert "h-new" in result.content

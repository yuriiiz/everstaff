"""DelegateTaskTool must attach child HITL requests as metadata on ToolResult."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from everstaff.agents.delegate_task_tool import DelegateTaskTool
from everstaff.protocols import (
    HitlRequest, HumanApprovalRequired, ToolResult,
)


@pytest.mark.asyncio
async def test_delegate_attaches_child_hitl_on_escalation():
    """When child raises HumanApprovalRequired, ToolResult must carry _child_hitl_requests."""
    from everstaff.schema.agent_spec import SubAgentSpec
    spec = MagicMock(spec=SubAgentSpec)
    spec.name = "child"
    spec.to_agent_spec.return_value = MagicMock(agent_name="child")

    env = MagicMock()
    tool = DelegateTaskTool(specs=[spec], env=env, parent_session_id="parent-sess")

    child_hitl = HitlRequest(
        hitl_id="h-child", type="approve_reject", prompt="OK?",
        origin_session_id="", origin_agent_name="",
    )

    mock_runtime = MagicMock()
    mock_runtime.run = AsyncMock(side_effect=HumanApprovalRequired([child_hitl]))
    mock_runtime.stats = None
    mock_ctx = MagicMock()
    mock_ctx.session_id = "child-sess-1"

    with patch("everstaff.agents.delegate_task_tool.AgentBuilder") as MockBuilder:
        MockBuilder.return_value.build = AsyncMock(return_value=(mock_runtime, mock_ctx))
        with patch.object(tool, "_fire_subagent_start", new_callable=AsyncMock, return_value="do it"):
            result = await tool.execute({"agent_name": "child", "prompt": "do it"})

    assert hasattr(result, '_child_hitl_requests')
    assert len(result._child_hitl_requests) == 1
    assert result._child_hitl_requests[0].hitl_id == "h-child"
    # Should also have origin metadata set
    assert result._child_hitl_requests[0].origin_session_id == "child-sess-1"
    assert result._child_hitl_requests[0].origin_agent_name == "child"


@pytest.mark.asyncio
async def test_delegate_attaches_child_hitl_on_resume_escalation():
    """When _resume_child raises HumanApprovalRequired, ToolResult must carry _child_hitl_requests."""
    import json
    from everstaff.schema.agent_spec import SubAgentSpec
    spec = MagicMock(spec=SubAgentSpec)
    spec.name = "child"
    spec.to_agent_spec.return_value = MagicMock(agent_name="child")

    env = MagicMock()
    # Provide a valid session so the new existence check passes
    session_data = {"messages": [{"role": "user", "content": "do it"}], "hitl_requests": []}
    mock_file_store = AsyncMock()
    mock_file_store.read = AsyncMock(return_value=json.dumps(session_data).encode())
    env.build_file_store.return_value = mock_file_store

    tool = DelegateTaskTool(specs=[spec], env=env, parent_session_id="parent-sess")

    child_hitl = HitlRequest(
        hitl_id="h-resume", type="approve_reject", prompt="OK again?",
        origin_session_id="", origin_agent_name="",
    )

    mock_runtime = MagicMock()
    mock_runtime.run = AsyncMock(side_effect=HumanApprovalRequired([child_hitl]))
    mock_runtime.stats = None
    mock_ctx = MagicMock()
    mock_ctx.session_id = "child-sess-resume"

    with patch("everstaff.agents.delegate_task_tool.AgentBuilder") as MockBuilder:
        MockBuilder.return_value.build = AsyncMock(return_value=(mock_runtime, mock_ctx))
        with patch.object(tool, "_resolve_child_hitl", new_callable=AsyncMock):
            result = await tool._resume_child(
                agent_name="child",
                prompt="continue",
                resume_session_id="child-sess-resume",
                hitl_response={"decision": "approved"},
            )

    assert hasattr(result, '_child_hitl_requests')
    assert len(result._child_hitl_requests) == 1
    assert result._child_hitl_requests[0].hitl_id == "h-resume"
    assert result._child_hitl_requests[0].origin_session_id == "child-sess-resume"
    assert result._child_hitl_requests[0].origin_agent_name == "child"

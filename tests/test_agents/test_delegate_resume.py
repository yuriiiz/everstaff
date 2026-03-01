"""DelegateTaskTool._resume_child must pass session_id to AgentBuilder, not use _ResumeEnv."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from everstaff.agents.delegate_task_tool import DelegateTaskTool
from everstaff.protocols import CancellationEvent


def _make_tool_with_mock_spec():
    from everstaff.schema.agent_spec import SubAgentSpec
    spec = MagicMock(spec=SubAgentSpec)
    spec.name = "child-agent"
    spec.to_agent_spec.return_value = MagicMock(agent_name="child-agent")
    env = MagicMock()
    tool = DelegateTaskTool(
        specs=[spec],
        env=env,
        parent_session_id="parent-sess",
    )
    return tool, spec, env


@pytest.mark.asyncio
async def test_resume_child_passes_session_id_to_builder():
    """_resume_child must call AgentBuilder with session_id=resume_session_id."""
    tool, spec, env = _make_tool_with_mock_spec()

    mock_runtime = MagicMock()
    mock_runtime.run = AsyncMock(return_value="done")
    mock_runtime.stats = None
    mock_ctx = MagicMock()
    mock_ctx.session_id = "child-sess-123"

    with patch("everstaff.agents.delegate_task_tool.AgentBuilder") as MockBuilder:
        MockBuilder.return_value.build = AsyncMock(return_value=(mock_runtime, mock_ctx))
        with patch.object(tool, "_resolve_child_hitl", new_callable=AsyncMock):
            with patch.object(tool, "_fire_subagent_end", new_callable=AsyncMock):
                result = await tool._resume_child(
                    "child-agent", "continue", "child-sess-123", {"decision": "approved"}
                )

        # Key assertion: AgentBuilder was called with session_id keyword
        MockBuilder.assert_called_once()
        _, call_kwargs = MockBuilder.call_args
        assert call_kwargs.get("session_id") == "child-sess-123", \
            f"AgentBuilder must receive session_id='child-sess-123', got {call_kwargs}"


@pytest.mark.asyncio
async def test_resume_child_does_not_use_resume_env():
    """After cleanup, _ResumeEnv should no longer exist in the module."""
    import everstaff.agents.delegate_task_tool as mod
    assert not hasattr(mod, "_ResumeEnv"), "_ResumeEnv should be removed"
    # Also check it's not defined as a nested class anywhere accessible
    source = open(mod.__file__).read()
    assert "_ResumeEnv" not in source, "_ResumeEnv class should be completely removed from source"

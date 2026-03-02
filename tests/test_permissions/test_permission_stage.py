"""Test PermissionStage with DynamicPermissionChecker HITL flow."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from everstaff.protocols import PermissionResult, HumanApprovalRequired, ToolResult
from everstaff.tools.stages import PermissionStage
from everstaff.tools.pipeline import ToolCallContext


def _make_ctx(tool_name="Bash", args=None, tool_call_id="tc-1"):
    ctx = MagicMock(spec=ToolCallContext)
    ctx.tool_name = tool_name
    ctx.args = args or {}
    ctx.tool_call_id = tool_call_id
    ctx.agent_context = MagicMock()
    ctx.agent_context.session_id = "sess-1"
    return ctx


@pytest.mark.asyncio
async def test_permission_stage_allowed():
    checker = MagicMock()
    checker.check.return_value = PermissionResult(allowed=True)
    stage = PermissionStage(checker)
    next_fn = AsyncMock(return_value=ToolResult(tool_call_id="tc-1", content="ok"))

    result = await stage(_make_ctx(), next_fn)
    assert result.content == "ok"
    next_fn.assert_awaited_once()


@pytest.mark.asyncio
async def test_permission_stage_denied():
    checker = MagicMock()
    checker.check.return_value = PermissionResult(allowed=False, reason="denied")
    stage = PermissionStage(checker)
    next_fn = AsyncMock()

    result = await stage(_make_ctx(), next_fn)
    assert result.is_error
    assert "denied" in result.content.lower()
    next_fn.assert_not_awaited()


@pytest.mark.asyncio
async def test_permission_stage_needs_hitl_raises():
    checker = MagicMock()
    checker.check.return_value = PermissionResult(allowed=False, needs_hitl=True)
    stage = PermissionStage(checker)
    next_fn = AsyncMock()

    with pytest.raises(HumanApprovalRequired) as exc_info:
        await stage(_make_ctx(tool_name="Write", tool_call_id="tc-42"), next_fn)

    assert len(exc_info.value.requests) == 1
    req = exc_info.value.requests[0]
    assert req.type == "tool_permission"
    assert req.tool_name == "Write"
    assert req.tool_call_id == "tc-42"
    assert "approve_once" in req.options
    assert "approve_session" in req.options
    assert "approve_permanent" in req.options
    assert "reject" in req.options
    next_fn.assert_not_awaited()

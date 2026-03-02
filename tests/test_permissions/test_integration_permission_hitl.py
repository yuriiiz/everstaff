"""Integration test: full tool permission HITL cycle."""
import pytest
from unittest.mock import MagicMock, AsyncMock

from everstaff.permissions.rule_checker import RuleBasedChecker
from everstaff.permissions.dynamic_checker import DynamicPermissionChecker
from everstaff.tools.stages import PermissionStage, ExecutionStage
from everstaff.tools.pipeline import ToolCallPipeline, ToolCallContext
from everstaff.protocols import HumanApprovalRequired, ToolResult


@pytest.mark.asyncio
async def test_full_hitl_cycle():
    """Tool not in allow -> HITL raised -> session grant added -> re-check passes."""
    agent_checker = RuleBasedChecker(allow=["Read"], deny=[])
    checker = DynamicPermissionChecker(
        global_checker=None,
        agent_checker=agent_checker,
        session_grants=[],
        is_system_tool=lambda _: False,
    )

    # 1. Bash triggers HITL
    result = checker.check("Bash", {})
    assert result.needs_hitl

    # 2. Simulate HITL resolution: user approves for session
    checker.add_session_grant("Bash")

    # 3. Bash is now allowed via session grant
    result = checker.check("Bash", {})
    assert result.allowed

    # 4. Read was always allowed
    assert checker.check("Read", {}).allowed

    # 5. Write still triggers HITL
    result = checker.check("Write", {})
    assert result.needs_hitl


@pytest.mark.asyncio
async def test_pipeline_hitl_raises_then_grants():
    """Pipeline raises HITL for unallowed tool, then passes after session grant."""
    agent_checker = RuleBasedChecker(allow=["Read"], deny=[])
    checker = DynamicPermissionChecker(
        global_checker=None,
        agent_checker=agent_checker,
        session_grants=[],
        is_system_tool=lambda _: False,
    )

    mock_registry = MagicMock()
    mock_registry.execute = AsyncMock(
        return_value=ToolResult(tool_call_id="tc-1", content="ok")
    )

    pipeline = ToolCallPipeline([
        PermissionStage(checker),
        ExecutionStage(mock_registry),
    ])

    ctx = ToolCallContext(
        tool_name="Bash",
        args={"command": "ls"},
        agent_context=MagicMock(),
        tool_call_id="tc-1",
    )

    # First call: HITL raised
    with pytest.raises(HumanApprovalRequired) as exc_info:
        await pipeline.execute(ctx)

    req = exc_info.value.requests[0]
    assert req.type == "tool_permission"
    assert req.tool_name == "Bash"

    # Session grant added
    checker.add_session_grant("Bash")

    # Second call: passes through
    result = await pipeline.execute(ctx)
    assert result.content == "ok"


@pytest.mark.asyncio
async def test_denied_tool_never_passes():
    """Denied tool returns error, not HITL."""
    agent_checker = RuleBasedChecker(allow=[], deny=["Bash"])
    checker = DynamicPermissionChecker(
        global_checker=None,
        agent_checker=agent_checker,
        session_grants=["Bash"],  # even with session grant
        is_system_tool=lambda _: False,
    )

    mock_registry = MagicMock()
    mock_registry.execute = AsyncMock()

    pipeline = ToolCallPipeline([
        PermissionStage(checker),
        ExecutionStage(mock_registry),
    ])

    ctx = ToolCallContext(
        tool_name="Bash",
        args={},
        agent_context=MagicMock(),
        tool_call_id="tc-1",
    )

    # Should NOT raise HITL, should return error
    result = await pipeline.execute(ctx)
    assert result.is_error
    assert "denied" in result.content.lower()
    mock_registry.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_system_tool_always_passes():
    """System tools bypass permission check entirely."""
    agent_checker = RuleBasedChecker(allow=[], deny=[])
    checker = DynamicPermissionChecker(
        global_checker=None,
        agent_checker=agent_checker,
        session_grants=[],
        is_system_tool=lambda name: name == "request_human_input",
    )

    mock_registry = MagicMock()
    mock_registry.execute = AsyncMock(
        return_value=ToolResult(tool_call_id="tc-1", content="hitl")
    )

    pipeline = ToolCallPipeline([
        PermissionStage(checker),
        ExecutionStage(mock_registry),
    ])

    ctx = ToolCallContext(
        tool_name="request_human_input",
        args={"prompt": "test"},
        agent_context=MagicMock(),
        tool_call_id="tc-1",
    )

    result = await pipeline.execute(ctx)
    assert result.content == "hitl"
    mock_registry.execute.assert_awaited_once()

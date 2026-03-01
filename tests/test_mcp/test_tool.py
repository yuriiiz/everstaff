# tests/test_mcp/test_tool.py
import pytest
from unittest.mock import AsyncMock, MagicMock


def _make_definition():
    from everstaff.protocols import ToolDefinition
    return ToolDefinition(name="echo", description="echo back", parameters={})


@pytest.mark.asyncio
async def test_mcp_tool_returns_tool_result():
    """MCPTool.execute() must return ToolResult, not str."""
    from everstaff.mcp_client.tool import MCPTool
    from everstaff.protocols import ToolResult

    mock_session = AsyncMock()
    mock_block = MagicMock()
    mock_block.text = "hello"
    mock_session.call_tool.return_value = MagicMock(content=[mock_block])

    tool = MCPTool(session=mock_session, definition_=_make_definition(), tool_call_id="tc-1")
    result = await tool.execute({"message": "hello"})

    assert isinstance(result, ToolResult)
    assert result.content == "hello"
    assert result.is_error is False


@pytest.mark.asyncio
async def test_mcp_tool_implements_tool_protocol():
    """MCPTool must satisfy the Tool protocol (runtime_checkable)."""
    from everstaff.mcp_client.tool import MCPTool
    from everstaff.protocols import Tool

    mock_session = AsyncMock()
    tool = MCPTool(session=mock_session, definition_=_make_definition(), tool_call_id="tc-1")
    assert isinstance(tool, Tool)


@pytest.mark.asyncio
async def test_mcp_tool_timeout_returns_error_result():
    """Timeout must return ToolResult with is_error=True."""
    import asyncio
    from everstaff.mcp_client.tool import MCPTool
    from everstaff.protocols import ToolResult

    mock_session = AsyncMock()
    mock_session.call_tool.side_effect = asyncio.TimeoutError()

    tool = MCPTool(session=mock_session, definition_=_make_definition(), tool_call_id="tc-1")
    result = await tool.execute({})

    assert isinstance(result, ToolResult)
    assert result.is_error is True
    assert "timed out" in result.content


@pytest.mark.asyncio
async def test_mcp_tool_exception_returns_error_result():
    """Generic exception must return ToolResult with is_error=True."""
    from everstaff.mcp_client.tool import MCPTool
    from everstaff.protocols import ToolResult

    mock_session = AsyncMock()
    mock_session.call_tool.side_effect = RuntimeError("boom")

    tool = MCPTool(session=mock_session, definition_=_make_definition(), tool_call_id="tc-1")
    result = await tool.execute({})

    assert isinstance(result, ToolResult)
    assert result.is_error is True
    assert "boom" in result.content

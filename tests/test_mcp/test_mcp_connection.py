"""Tests for MCPConnection timeout threading."""
from __future__ import annotations

from unittest.mock import MagicMock, AsyncMock
import pytest

from everstaff.schema.agent_spec import MCPServerSpec


@pytest.mark.asyncio
async def test_discover_tools_passes_timeout_to_mcp_tool():
    """MCPConnection._discover_tools passes spec.timeout to each MCPTool."""
    spec = MCPServerSpec(
        name="test-server",
        transport="stdio",
        command="echo",
        timeout=120.0,
    )

    from everstaff.mcp_client.connection import MCPConnection
    conn = MCPConnection(spec)

    # Mock session.list_tools
    mock_tool_schema = MagicMock()
    mock_tool_schema.name = "some_tool"
    mock_tool_schema.description = "A tool"
    mock_tool_schema.inputSchema = {"properties": {}, "required": []}

    mock_session = MagicMock()
    mock_session.list_tools = AsyncMock(
        return_value=MagicMock(tools=[mock_tool_schema])
    )

    tools = await conn._discover_tools(mock_session)
    assert len(tools) == 1
    assert tools[0]._timeout_seconds == 120.0

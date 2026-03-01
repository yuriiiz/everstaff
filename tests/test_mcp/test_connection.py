# tests/test_mcp/test_connection.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_spec(name="test-server"):
    from everstaff.schema.agent_spec import MCPServerSpec
    return MCPServerSpec(name=name, command="python", args=["-c", "pass"])


@pytest.mark.asyncio
async def test_connection_discover_tools_returns_mcp_tools():
    """_discover_tools() wraps each MCP tool as MCPTool."""
    from everstaff.mcp_client.connection import MCPConnection
    from everstaff.mcp_client.tool import MCPTool

    mock_tool = MagicMock()
    mock_tool.name = "echo"
    mock_tool.description = "echo back"
    mock_tool.inputSchema = {
        "properties": {"message": {"type": "string", "description": "msg"}},
        "required": ["message"],
    }

    mock_session = AsyncMock()
    mock_session.list_tools.return_value = MagicMock(tools=[mock_tool])

    conn = MCPConnection(_make_spec())
    tools = await conn._discover_tools(mock_session)

    assert len(tools) == 1
    assert isinstance(tools[0], MCPTool)
    assert tools[0].definition.name == "echo"


def test_connection_converts_input_schema_to_tool_definition():
    """_tool_definition() converts inputSchema properties to parameters dict."""
    from everstaff.mcp_client.connection import MCPConnection
    from everstaff.schema.agent_spec import MCPServerSpec

    spec = MCPServerSpec(name="srv", command="python", args=[])
    conn = MCPConnection(spec)

    mock_tool = MagicMock()
    mock_tool.name = "add"
    mock_tool.description = "add numbers"
    mock_tool.inputSchema = {
        "properties": {
            "a": {"type": "number", "description": "first"},
            "b": {"type": "number", "description": "second"},
        },
        "required": ["a", "b"],
    }

    defn = conn._tool_definition(mock_tool)
    assert defn.name == "add"
    assert "a" in defn.parameters
    assert defn.parameters["a"]["type"] == "number"
    assert defn.parameters["a"]["required"] is True
    assert defn.parameters["b"]["required"] is True

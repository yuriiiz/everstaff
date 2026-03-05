# tests/test_mcp/test_provider.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_spec(name="srv"):
    from everstaff.schema.agent_spec import MCPServerSpec
    return MCPServerSpec(name=name, command="python", args=[])


def _make_mock_tool(name="echo"):
    from everstaff.protocols import ToolDefinition
    from everstaff.mcp_client.tool import MCPTool
    defn = ToolDefinition(name=name, description="test tool", parameters={})
    session = AsyncMock()
    return MCPTool(session=session, definition_=defn)


@pytest.mark.asyncio
async def test_provider_get_tools_returns_all_connected_tools():
    """get_tools() aggregates tools from all connected servers."""
    from everstaff.mcp_client.provider import DefaultMcpProvider

    tool_a = _make_mock_tool("tool_a")
    tool_b = _make_mock_tool("tool_b")

    with patch("everstaff.mcp_client.provider.MCPConnection") as MockConn:
        instance = AsyncMock()
        instance.connect = AsyncMock(return_value=[tool_a, tool_b])
        instance.disconnect = AsyncMock()
        MockConn.return_value = instance

        provider = DefaultMcpProvider([_make_spec()])
        await provider.connect_all()

    tools = provider.get_tools()
    assert len(tools) == 2
    assert tools[0].definition.name == "tool_a"


@pytest.mark.asyncio
async def test_provider_get_tools_empty_when_no_servers():
    from everstaff.mcp_client.provider import DefaultMcpProvider

    provider = DefaultMcpProvider([])
    await provider.connect_all()
    assert provider.get_tools() == []


def test_provider_get_prompt_injection_lists_tool_names():
    """get_prompt_injection() uses section-header format consistent with sub-agents/skills.

    Format must be:
      ## MCP Tools
      - **tool_name**: description
    NOT a plain inline sentence like "You have access to the following MCP tools: echo".
    """
    from everstaff.mcp_client.provider import DefaultMcpProvider

    tool = _make_mock_tool("echo")
    provider = DefaultMcpProvider([])
    provider._tools = [tool]

    injection = provider.get_prompt_injection()
    assert "echo" in injection
    # Must use section-header format, not inline sentence
    assert "## MCP Tools" in injection, (
        f"MCP injection must use '## MCP Tools' section header. Got: {injection!r}"
    )
    assert "- **echo**" in injection, (
        f"MCP injection must list tools as '- **name**'. Got: {injection!r}"
    )


@pytest.mark.asyncio
async def test_provider_disconnect_all_closes_connections():
    from everstaff.mcp_client.provider import DefaultMcpProvider

    with patch("everstaff.mcp_client.provider.MCPConnection") as MockConn:
        instance = AsyncMock()
        instance.connect = AsyncMock(return_value=[])
        instance.disconnect = AsyncMock()
        MockConn.return_value = instance

        provider = DefaultMcpProvider([_make_spec()])
        await provider.connect_all()
        await provider.disconnect_all()

        instance.disconnect.assert_called_once()


@pytest.mark.asyncio
async def test_provider_connect_all_runs_in_parallel():
    """connect_all() should connect to multiple servers concurrently, not sequentially."""
    import asyncio
    from everstaff.mcp_client.provider import DefaultMcpProvider

    call_order = []

    async def slow_connect(self_conn):
        name = self_conn._spec.name
        call_order.append(f"{name}_start")
        await asyncio.sleep(0.05)
        call_order.append(f"{name}_end")
        return [_make_mock_tool(f"tool_{name}")]

    specs = [_make_spec("srv1"), _make_spec("srv2"), _make_spec("srv3")]

    with patch("everstaff.mcp_client.provider.MCPConnection") as MockConn:
        instances = []
        def make_conn(spec):
            inst = AsyncMock()
            inst._spec = spec
            inst.connect = lambda: slow_connect(inst)
            inst.disconnect = AsyncMock()
            instances.append(inst)
            return inst
        MockConn.side_effect = make_conn

        provider = DefaultMcpProvider(specs)
        await provider.connect_all()

    assert len(provider.get_tools()) == 3
    starts = [i for i, x in enumerate(call_order) if x.endswith("_start")]
    ends = [i for i, x in enumerate(call_order) if x.endswith("_end")]
    assert max(starts) < min(ends), f"Expected parallel execution, got: {call_order}"


@pytest.mark.asyncio
async def test_provider_aclose_calls_disconnect_all():
    """aclose() must call disconnect_all() on the provider."""
    from everstaff.mcp_client.provider import DefaultMcpProvider

    with patch("everstaff.mcp_client.provider.MCPConnection") as MockConn:
        instance = AsyncMock()
        instance.connect = AsyncMock(return_value=[])
        instance.disconnect = AsyncMock()
        MockConn.return_value = instance

        provider = DefaultMcpProvider([_make_spec()])
        await provider.connect_all()
        await provider.aclose()

        instance.disconnect.assert_called_once()

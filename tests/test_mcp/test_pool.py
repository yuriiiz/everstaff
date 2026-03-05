"""Tests for McpConnectionPool — cross-session MCP connection reuse with idle cleanup."""
import asyncio
import pytest
from unittest.mock import AsyncMock, patch

from everstaff.schema.agent_spec import MCPServerSpec
from everstaff.protocols import ToolDefinition


def _make_spec(name="srv", command="python"):
    return MCPServerSpec(name=name, command=command, args=[])


def _make_mock_tool(name="echo"):
    from everstaff.mcp_client.tool import MCPTool
    defn = ToolDefinition(name=name, description="test", parameters={})
    return MCPTool(session=AsyncMock(), definition_=defn)


@pytest.mark.asyncio
async def test_pool_acquire_creates_new_connection():
    """First acquire for a spec creates a new connection."""
    from everstaff.mcp_client.pool import McpConnectionPool

    pool = McpConnectionPool(idle_timeout=60)
    tool = _make_mock_tool("tool_a")

    with patch("everstaff.mcp_client.pool.MCPConnection") as MockConn:
        inst = AsyncMock()
        inst.connect = AsyncMock(return_value=[tool])
        inst.disconnect = AsyncMock()
        MockConn.return_value = inst

        conn, tools = await pool.acquire(_make_spec("srv1"))

    assert len(tools) == 1
    assert tools[0].definition.name == "tool_a"


@pytest.mark.asyncio
async def test_pool_acquire_reuses_idle_connection():
    """Second acquire for same spec reuses the pooled connection."""
    from everstaff.mcp_client.pool import McpConnectionPool

    pool = McpConnectionPool(idle_timeout=60)
    tool = _make_mock_tool("tool_a")

    with patch("everstaff.mcp_client.pool.MCPConnection") as MockConn:
        inst = AsyncMock()
        inst.connect = AsyncMock(return_value=[tool])
        inst.disconnect = AsyncMock()
        MockConn.return_value = inst

        conn1, _ = await pool.acquire(_make_spec("srv1"))
        await pool.release(conn1)
        conn2, _ = await pool.acquire(_make_spec("srv1"))

    assert conn1 is conn2
    inst.connect.assert_awaited_once()


@pytest.mark.asyncio
async def test_pool_release_returns_connection():
    """Released connections become available for reuse."""
    from everstaff.mcp_client.pool import McpConnectionPool

    pool = McpConnectionPool(idle_timeout=60)

    with patch("everstaff.mcp_client.pool.MCPConnection") as MockConn:
        inst = AsyncMock()
        inst.connect = AsyncMock(return_value=[])
        inst.disconnect = AsyncMock()
        MockConn.return_value = inst

        conn, _ = await pool.acquire(_make_spec("srv1"))
        assert pool.active_count == 1
        await pool.release(conn)
        assert pool.active_count == 0
        assert pool.idle_count == 1


@pytest.mark.asyncio
async def test_pool_close_disconnects_all():
    """close() disconnects all idle and active connections."""
    from everstaff.mcp_client.pool import McpConnectionPool

    pool = McpConnectionPool(idle_timeout=60)

    with patch("everstaff.mcp_client.pool.MCPConnection") as MockConn:
        inst = AsyncMock()
        inst.connect = AsyncMock(return_value=[])
        inst.disconnect = AsyncMock()
        MockConn.return_value = inst

        conn, _ = await pool.acquire(_make_spec("srv1"))
        await pool.release(conn)
        await pool.close()

    inst.disconnect.assert_awaited_once()
    assert pool.idle_count == 0


@pytest.mark.asyncio
async def test_pool_idle_cleanup():
    """Connections idle longer than timeout get cleaned up."""
    from everstaff.mcp_client.pool import McpConnectionPool

    pool = McpConnectionPool(idle_timeout=0.05)

    with patch("everstaff.mcp_client.pool.MCPConnection") as MockConn:
        inst = AsyncMock()
        inst.connect = AsyncMock(return_value=[])
        inst.disconnect = AsyncMock()
        MockConn.return_value = inst

        conn, _ = await pool.acquire(_make_spec("srv1"))
        await pool.release(conn)
        assert pool.idle_count == 1

        await asyncio.sleep(0.1)
        await pool.cleanup_idle()

        assert pool.idle_count == 0
        inst.disconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_pool_reuse_across_providers():
    """Simulates two sessions using the same pool — second session reuses connection."""
    from everstaff.mcp_client.provider import PooledMcpProvider
    from everstaff.mcp_client.pool import McpConnectionPool

    pool = McpConnectionPool(idle_timeout=60)
    tool = _make_mock_tool("shared_tool")

    with patch("everstaff.mcp_client.pool.MCPConnection") as MockConn:
        inst = AsyncMock()
        inst.connect = AsyncMock(return_value=[tool])
        inst.disconnect = AsyncMock()
        MockConn.return_value = inst

        # Session 1: acquire + release
        p1 = PooledMcpProvider([_make_spec("srv1")], pool=pool)
        await p1.connect_all()
        assert pool.active_count == 1
        await p1.aclose()
        assert pool.idle_count == 1

        # Session 2: should reuse
        p2 = PooledMcpProvider([_make_spec("srv1")], pool=pool)
        await p2.connect_all()
        assert pool.active_count == 1

    # connect() was called only once total (reuse!)
    inst.connect.assert_awaited_once()

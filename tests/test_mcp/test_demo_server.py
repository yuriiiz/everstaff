# tests/test_mcp/test_demo_server.py
"""Integration test: start demo MCP server as subprocess and discover its tools."""
import pytest
import sys
from pathlib import Path


@pytest.mark.asyncio
async def test_demo_server_exposes_echo_add_get_time():
    """Demo server must advertise echo, add, and get_time tools via stdio."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from contextlib import AsyncExitStack

    server_path = Path(__file__).parent.parent.parent / "examples" / "demo_mcp" / "server.py"
    assert server_path.exists(), f"Demo server not found at {server_path}"

    params = StdioServerParameters(
        command=sys.executable,
        args=[str(server_path)],
    )

    async with AsyncExitStack() as stack:
        transport = await stack.enter_async_context(stdio_client(params))
        session = await stack.enter_async_context(ClientSession(*transport))
        await session.initialize()

        response = await session.list_tools()
        tool_names = {t.name for t in response.tools}

    assert "echo" in tool_names
    assert "add" in tool_names
    assert "get_time" in tool_names


@pytest.mark.asyncio
async def test_demo_server_echo_returns_input():
    import sys
    from pathlib import Path
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from contextlib import AsyncExitStack

    server_path = Path(__file__).parent.parent.parent / "examples" / "demo_mcp" / "server.py"
    params = StdioServerParameters(command=sys.executable, args=[str(server_path)])

    async with AsyncExitStack() as stack:
        transport = await stack.enter_async_context(stdio_client(params))
        session = await stack.enter_async_context(ClientSession(*transport))
        await session.initialize()
        result = await session.call_tool("echo", {"message": "hello MCP"})

    assert any(
        hasattr(b, "text") and "hello MCP" in b.text
        for b in result.content
    )


@pytest.mark.asyncio
async def test_demo_server_add_returns_sum():
    import sys
    from pathlib import Path
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from contextlib import AsyncExitStack

    server_path = Path(__file__).parent.parent.parent / "examples" / "demo_mcp" / "server.py"
    params = StdioServerParameters(command=sys.executable, args=[str(server_path)])

    async with AsyncExitStack() as stack:
        transport = await stack.enter_async_context(stdio_client(params))
        session = await stack.enter_async_context(ClientSession(*transport))
        await session.initialize()
        result = await session.call_tool("add", {"a": 3, "b": 4})

    assert any(
        hasattr(b, "text") and "7" in b.text
        for b in result.content
    )

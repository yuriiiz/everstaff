# src/mcp_client/connection.py
"""MCPConnection — manages lifecycle of a single MCP server connection."""
from __future__ import annotations

import logging
from contextlib import AsyncExitStack
from typing import Any, TYPE_CHECKING

from everstaff.protocols import ToolDefinition

if TYPE_CHECKING:
    from everstaff.schema.agent_spec import MCPServerSpec
    from everstaff.mcp_client.tool import MCPTool

logger = logging.getLogger(__name__)


class MCPConnection:
    """Manages a connection to a single MCP server."""

    def __init__(self, spec: "MCPServerSpec") -> None:
        self._spec = spec
        self._exit_stack: AsyncExitStack | None = None

    def _tool_definition(self, t: Any) -> ToolDefinition:
        """Convert MCP tool schema to ToolDefinition with parameters as dict."""
        input_schema = getattr(t, "inputSchema", None) or {}
        parameters: dict[str, Any] = {}
        if isinstance(input_schema, dict) and "properties" in input_schema:
            required_set = set(input_schema.get("required", []))
            for pname, pschema in input_schema["properties"].items():
                parameters[pname] = {
                    "type": pschema.get("type", "string"),
                    "description": pschema.get("description", ""),
                    "required": pname in required_set,
                }
        return ToolDefinition(
            name=t.name,
            description=getattr(t, "description", "") or "",
            parameters=parameters,
        )

    async def _discover_tools(self, session: Any) -> list["MCPTool"]:
        import importlib
        mcp_tool_mod = importlib.import_module("everstaff.mcp_client.tool")
        MCPTool = mcp_tool_mod.MCPTool

        tools_response = await session.list_tools()
        result = []
        for t in tools_response.tools:
            defn = self._tool_definition(t)
            result.append(MCPTool(session=session, definition_=defn))
        return result

    async def connect(self) -> list["MCPTool"]:
        """Connect to MCP server and return list of discovered MCPTool."""
        logger.debug("Connecting to MCP server: %s %s", self._spec.command, self._spec.args)
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError:
            raise ImportError("MCP package not installed. Run: pip install mcp")

        self._exit_stack = AsyncExitStack()
        server_params = StdioServerParameters(
            command=self._spec.command,
            args=self._spec.args,
            env=self._spec.env or None,
        )
        transport = await self._exit_stack.enter_async_context(
            stdio_client(server_params)
        )
        read_stream, write_stream = transport
        session = await self._exit_stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await session.initialize()
        tools = await self._discover_tools(session)
        logger.debug("MCP server connected, discovered %d tool(s)", len(tools))
        return tools

    async def disconnect(self) -> None:
        if self._exit_stack:
            try:
                await self._exit_stack.aclose()
            except Exception:
                pass
            self._exit_stack = None

# src/mcp_client/provider.py
"""DefaultMcpProvider — aggregates tools from multiple MCP server connections."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from everstaff.protocols import Tool
from .connection import MCPConnection

if TYPE_CHECKING:
    from everstaff.schema.agent_spec import MCPServerSpec

logger = logging.getLogger(__name__)


class DefaultMcpProvider:
    """Manages multiple MCP server connections and exposes their tools."""

    def __init__(self, specs: list["MCPServerSpec"]) -> None:
        self._specs = specs
        self._connections: list = []
        self._tools: list[Tool] = []

    async def connect_all(self) -> None:
        """Connect to all configured MCP servers in parallel and discover their tools."""
        import asyncio

        async def _connect_one(spec):
            conn = MCPConnection(spec)
            try:
                tools = await conn.connect()
                return conn, tools
            except Exception as e:
                logger.warning(
                    "Failed to connect to MCP server '%s': %s", spec.name, e
                )
                return None, []

        results = await asyncio.gather(*[_connect_one(s) for s in self._specs])
        for conn, tools in results:
            if conn is not None:
                self._connections.append(conn)
                self._tools.extend(tools)

    async def disconnect_all(self) -> None:
        """Disconnect from all MCP servers."""
        for conn in self._connections:
            await conn.disconnect()
        self._connections.clear()
        self._tools.clear()

    async def aclose(self) -> None:
        """Alias for disconnect_all(); satisfies McpProvider protocol."""
        await self.disconnect_all()

    def get_tools(self) -> list[Tool]:
        return list(self._tools)

    def get_prompt_injection(self) -> str:
        if not self._tools:
            return ""
        lines = ["## MCP Tools", ""]
        for tool in self._tools:
            defn = tool.definition
            desc = defn.description or ""
            lines.append(f"- **{defn.name}**: {desc}" if desc else f"- **{defn.name}**")
        return "\n".join(lines)

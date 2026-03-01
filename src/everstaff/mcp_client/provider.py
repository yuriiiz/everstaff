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
        """Connect to all configured MCP servers and discover their tools."""
        for spec in self._specs:
            conn = MCPConnection(spec)
            try:
                tools = await conn.connect()
                self._connections.append(conn)
                self._tools.extend(tools)
            except Exception as e:
                logger.warning(
                    "Failed to connect to MCP server '%s': %s", spec.name, e
                )

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

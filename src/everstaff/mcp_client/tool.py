# src/mcp_client/tool.py
"""MCPTool — wraps a single MCP tool, implements the Tool protocol."""
from __future__ import annotations

import asyncio
from typing import Any

from everstaff.protocols import ToolDefinition, ToolResult


class MCPTool:
    """Wraps a single MCP tool. Implements the Tool protocol."""

    def __init__(
        self,
        session: Any,
        definition_: ToolDefinition,
        tool_call_id: str = "",
    ) -> None:
        self._session = session
        self._definition = definition_
        self._tool_call_id = tool_call_id

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            result = await asyncio.wait_for(
                self._session.call_tool(self._definition.name, arguments=args),
                timeout=30.0,
            )
            parts = []
            for block in result.content:
                if hasattr(block, "text"):
                    parts.append(block.text)
                else:
                    parts.append(str(block))
            content = "\n".join(parts) if parts else ""
            return ToolResult(
                tool_call_id=self._tool_call_id,
                content=content,
                is_error=False,
            )
        except asyncio.TimeoutError:
            return ToolResult(
                tool_call_id=self._tool_call_id,
                content=f"Error: MCP tool '{self._definition.name}' timed out after 30s",
                is_error=True,
            )
        except Exception as e:
            return ToolResult(
                tool_call_id=self._tool_call_id,
                content=f"Error executing MCP tool '{self._definition.name}': {e}",
                is_error=True,
            )

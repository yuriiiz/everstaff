from __future__ import annotations

from typing import Any

from everstaff.protocols import HumanApprovalRequired, Tool, ToolDefinition, ToolResult


class DefaultToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        name = tool.definition.name
        if name in self._tools:
            raise ValueError(f"Tool '{name}' already registered")
        self._tools[name] = tool

    def register_native(self, tool: Any) -> None:
        """Register an object with .name or .definition.name, .execute(), and .definition."""
        name = tool.name if hasattr(tool, "name") else tool.definition.name
        self._tools[name] = tool

    def get_definitions(self) -> list[ToolDefinition]:
        return [t.definition for t in self._tools.values()]

    def has_tool(self, name: str) -> bool:
        return name in self._tools

    async def execute(self, name: str, args: dict[str, Any], tool_call_id: str) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(
                tool_call_id=tool_call_id,
                content=f"Unknown tool: '{name}'",
                is_error=True,
            )
        try:
            result = await tool.execute(args)
            if isinstance(result, str):
                return ToolResult(tool_call_id=tool_call_id, content=result, is_error=False)
            new_result = ToolResult(
                tool_call_id=tool_call_id,
                content=result.content,
                is_error=result.is_error,
                child_stats=result.child_stats,
            )
            # Propagate dynamic child HITL metadata for framework fallback tracking
            if hasattr(result, "_child_hitl_requests"):
                new_result._child_hitl_requests = result._child_hitl_requests
            return new_result
        except HumanApprovalRequired:
            raise   # propagate to AgentRuntime — do NOT convert to error result
        except Exception as exc:
            return ToolResult(
                tool_call_id=tool_call_id,
                content=f"Tool '{name}' raised: {exc}",
                is_error=True,
            )

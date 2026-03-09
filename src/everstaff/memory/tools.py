"""Agent-facing memory tools: search, write, delete."""
from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from everstaff.protocols import ToolDefinition, ToolResult

if TYPE_CHECKING:
    from everstaff.memory.mem0_client import Mem0Client

logger = logging.getLogger(__name__)


class SearchMemoryTool:
    """Search long-term memory for relevant facts."""

    def __init__(self, mem0: "Mem0Client", scope: dict[str, Any]) -> None:
        self._mem0 = mem0
        self._scope = {k: v for k, v in scope.items() if v is not None}

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="search_memory",
            description="Search long-term memory for relevant facts and context from previous interactions.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to search for in memory"},
                },
                "required": ["query"],
            },
        )

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        query = args.get("query", "")
        try:
            results = await self._mem0.search(query, **self._scope)
        except Exception as exc:
            logger.warning("search_memory failed: %s", exc)
            return ToolResult(tool_call_id="", content=f"Memory search failed: {exc}", is_error=True)
        if not results:
            return ToolResult(tool_call_id="", content="No results found.")
        lines = [f"- [{r.get('id', '?')}] {r.get('memory', str(r))}" for r in results]
        return ToolResult(tool_call_id="", content="\n".join(lines))


class WriteMemoryTool:
    """Write a fact to long-term memory."""

    def __init__(self, mem0: "Mem0Client", scope: dict[str, Any]) -> None:
        self._mem0 = mem0
        self._scope = {k: v for k, v in scope.items() if v is not None}

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="write_memory",
            description="Persist an important fact or insight to long-term memory for future reference.",
            parameters={
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "The fact or insight to remember"},
                },
                "required": ["content"],
            },
        )

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        content = args.get("content", "")
        try:
            result = await self._mem0.add_raw(content, **self._scope)
            return ToolResult(tool_call_id="", content=f"Memory saved. ({len(result)} entries processed)")
        except Exception as exc:
            logger.warning("write_memory failed: %s", exc)
            return ToolResult(tool_call_id="", content=f"Failed to save memory: {exc}", is_error=True)


class DeleteMemoryTool:
    """Delete a specific memory by ID."""

    def __init__(self, mem0: "Mem0Client", scope: dict[str, Any]) -> None:
        self._mem0 = mem0
        self._scope = {k: v for k, v in scope.items() if v is not None}

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="delete_memory",
            description="Delete a specific memory entry by its ID. Use search_memory first to find the ID.",
            parameters={
                "type": "object",
                "properties": {
                    "memory_id": {"type": "string", "description": "The ID of the memory to delete"},
                },
                "required": ["memory_id"],
            },
        )

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        memory_id = args.get("memory_id", "")
        try:
            await self._mem0.delete(memory_id)
            return ToolResult(tool_call_id="", content=f"Memory '{memory_id}' deleted.")
        except Exception as exc:
            logger.warning("delete_memory failed: %s", exc)
            return ToolResult(tool_call_id="", content=f"Failed to delete memory: {exc}", is_error=True)

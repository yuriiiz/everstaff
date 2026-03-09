"""MemoryToolProvider — auto-injects memory tools when memory is enabled."""
from __future__ import annotations

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from everstaff.memory.mem0_client import Mem0Client


class MemoryToolProvider:
    """Provides search/write/delete memory tools when mem0 is available."""

    def __init__(self, mem0: "Mem0Client | None", scope: dict[str, Any]) -> None:
        self._mem0 = mem0
        self._scope = scope

    def get_tools(self) -> list:
        if self._mem0 is None:
            return []
        from everstaff.memory.tools import SearchMemoryTool, WriteMemoryTool, DeleteMemoryTool
        return [
            SearchMemoryTool(self._mem0, self._scope),
            WriteMemoryTool(self._mem0, self._scope),
            DeleteMemoryTool(self._mem0, self._scope),
        ]

"""Tests for MemoryToolProvider."""
from unittest.mock import MagicMock


class TestMemoryToolProvider:
    def test_get_tools_returns_three(self):
        from everstaff.memory.tool_provider import MemoryToolProvider
        mem0 = MagicMock()
        provider = MemoryToolProvider(mem0, {"agent_id": "a1", "user_id": "u1"})
        tools = provider.get_tools()
        assert len(tools) == 3
        names = {t.definition.name for t in tools}
        assert names == {"search_memory", "write_memory", "delete_memory"}

    def test_get_tools_empty_when_no_mem0(self):
        from everstaff.memory.tool_provider import MemoryToolProvider
        provider = MemoryToolProvider(None, {})
        assert provider.get_tools() == []

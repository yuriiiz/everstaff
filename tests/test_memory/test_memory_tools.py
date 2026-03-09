"""Tests for memory tools (search, write, delete)."""
import pytest
from unittest.mock import AsyncMock, MagicMock


def _make_mock_mem0():
    mem0 = MagicMock()
    mem0.search = AsyncMock()
    mem0.add_raw = AsyncMock()
    mem0.delete = AsyncMock()
    return mem0


class TestSearchMemoryTool:
    def test_definition(self):
        from everstaff.memory.tools import SearchMemoryTool
        tool = SearchMemoryTool(_make_mock_mem0(), {"agent_id": "a1"})
        defn = tool.definition
        assert defn.name == "search_memory"
        assert "query" in defn.parameters["properties"]

    @pytest.mark.asyncio
    async def test_execute_returns_memories(self):
        from everstaff.memory.tools import SearchMemoryTool
        mem0 = _make_mock_mem0()
        mem0.search.return_value = [
            {"id": "m1", "memory": "likes python", "score": 0.9},
            {"id": "m2", "memory": "prefers dark mode", "score": 0.8},
        ]
        tool = SearchMemoryTool(mem0, {"agent_id": "a1", "user_id": "u1"})
        result = await tool.execute({"query": "preferences"})
        mem0.search.assert_called_once_with("preferences", agent_id="a1", user_id="u1")
        assert "likes python" in result.content
        assert "m1" in result.content

    @pytest.mark.asyncio
    async def test_execute_no_results(self):
        from everstaff.memory.tools import SearchMemoryTool
        mem0 = _make_mock_mem0()
        mem0.search.return_value = []
        tool = SearchMemoryTool(mem0, {"agent_id": "a1"})
        result = await tool.execute({"query": "unknown"})
        assert "no results" in result.content.lower()

    @pytest.mark.asyncio
    async def test_execute_filters_none_scope(self):
        from everstaff.memory.tools import SearchMemoryTool
        mem0 = _make_mock_mem0()
        mem0.search.return_value = []
        tool = SearchMemoryTool(mem0, {"agent_id": "a1", "user_id": None})
        await tool.execute({"query": "test"})
        mem0.search.assert_called_once_with("test", agent_id="a1")

    @pytest.mark.asyncio
    async def test_execute_error(self):
        from everstaff.memory.tools import SearchMemoryTool
        mem0 = _make_mock_mem0()
        mem0.search.side_effect = Exception("connection error")
        tool = SearchMemoryTool(mem0, {"agent_id": "a1"})
        result = await tool.execute({"query": "test"})
        assert result.is_error
        assert "connection error" in result.content


class TestWriteMemoryTool:
    def test_definition(self):
        from everstaff.memory.tools import WriteMemoryTool
        tool = WriteMemoryTool(_make_mock_mem0(), {"agent_id": "a1"})
        defn = tool.definition
        assert defn.name == "write_memory"
        assert "content" in defn.parameters["properties"]

    @pytest.mark.asyncio
    async def test_execute_writes_fact(self):
        from everstaff.memory.tools import WriteMemoryTool
        mem0 = _make_mock_mem0()
        mem0.add_raw.return_value = [{"id": "mem_new", "event": "ADD", "data": {"memory": "test"}}]
        tool = WriteMemoryTool(mem0, {"agent_id": "a1", "user_id": "u1"})
        result = await tool.execute({"content": "User prefers Chinese"})
        mem0.add_raw.assert_called_once_with("User prefers Chinese", agent_id="a1", user_id="u1")
        assert not result.is_error

    @pytest.mark.asyncio
    async def test_execute_error(self):
        from everstaff.memory.tools import WriteMemoryTool
        mem0 = _make_mock_mem0()
        mem0.add_raw.side_effect = Exception("write failed")
        tool = WriteMemoryTool(mem0, {"agent_id": "a1"})
        result = await tool.execute({"content": "something"})
        assert result.is_error
        assert "write failed" in result.content


class TestDeleteMemoryTool:
    def test_definition(self):
        from everstaff.memory.tools import DeleteMemoryTool
        tool = DeleteMemoryTool(_make_mock_mem0(), {"agent_id": "a1"})
        defn = tool.definition
        assert defn.name == "delete_memory"
        assert "memory_id" in defn.parameters["properties"]

    @pytest.mark.asyncio
    async def test_execute_deletes(self):
        from everstaff.memory.tools import DeleteMemoryTool
        mem0 = _make_mock_mem0()
        tool = DeleteMemoryTool(mem0, {"agent_id": "a1"})
        result = await tool.execute({"memory_id": "mem_123"})
        mem0.delete.assert_called_once_with("mem_123")
        assert not result.is_error

    @pytest.mark.asyncio
    async def test_execute_error(self):
        from everstaff.memory.tools import DeleteMemoryTool
        mem0 = _make_mock_mem0()
        mem0.delete.side_effect = Exception("not found")
        tool = DeleteMemoryTool(mem0, {"agent_id": "a1"})
        result = await tool.execute({"memory_id": "bad_id"})
        assert result.is_error

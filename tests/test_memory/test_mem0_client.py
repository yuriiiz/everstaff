"""Tests for Mem0Client wrapper."""
import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from everstaff.core.config import MemoryConfig
from everstaff.schema.model_config import ModelMapping


class TestMem0ClientParseModelId:
    def test_parse_openai_model(self):
        from everstaff.memory.mem0_client import Mem0Client
        assert Mem0Client._parse_model_id("openai/gpt-4.1-nano") == ("openai", "gpt-4.1-nano")

    def test_parse_anthropic_model(self):
        from everstaff.memory.mem0_client import Mem0Client
        assert Mem0Client._parse_model_id("anthropic/claude-haiku-4-5-20251001") == ("anthropic", "claude-haiku-4-5-20251001")

    def test_parse_bare_model(self):
        from everstaff.memory.mem0_client import Mem0Client
        assert Mem0Client._parse_model_id("gpt-4o") == ("openai", "gpt-4o")


@pytest.mark.asyncio
class TestMem0ClientAdd:
    async def test_add_calls_mem0_with_scope(self):
        with patch("everstaff.memory.mem0_client.Memory") as MockMemory:
            mock_instance = MagicMock()
            mock_instance.add.return_value = [{"id": "mem_1", "event": "ADD", "data": {"memory": "test"}}]
            MockMemory.from_config.return_value = mock_instance

            from everstaff.memory.mem0_client import Mem0Client
            config = MemoryConfig(enabled=True)
            mapping = ModelMapping(model_id="openai/gpt-4.1-nano")
            client = Mem0Client(config, mapping)

            messages = [{"role": "user", "content": "I like Python"}]
            result = await client.add(messages, user_id="u1", agent_id="a1")

            mock_instance.add.assert_called_once_with(messages, user_id="u1", agent_id="a1")
            assert len(result) == 1


@pytest.mark.asyncio
class TestMem0ClientSearch:
    async def test_search_filters_by_threshold(self):
        with patch("everstaff.memory.mem0_client.Memory") as MockMemory:
            mock_instance = MagicMock()
            mock_instance.search.return_value = [
                {"memory": "high relevance", "score": 0.9},
                {"memory": "low relevance", "score": 0.1},
            ]
            MockMemory.from_config.return_value = mock_instance

            from everstaff.memory.mem0_client import Mem0Client
            config = MemoryConfig(enabled=True, search_threshold=0.3)
            mapping = ModelMapping(model_id="openai/gpt-4.1-nano")
            client = Mem0Client(config, mapping)

            results = await client.search("test query", user_id="u1")

            assert len(results) == 1
            assert results[0]["memory"] == "high relevance"

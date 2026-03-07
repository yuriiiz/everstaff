"""Tests for Mem0Client wrapper."""
import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from everstaff.core.config import MemoryConfig


class TestMem0ClientParseEmbeddingModel:
    def test_parse_openai_embedding(self):
        from everstaff.memory.mem0_client import Mem0Client
        assert Mem0Client._parse_embedding_model("openai/text-embedding-3-small") == ("openai", "text-embedding-3-small")

    def test_parse_provider_embedding(self):
        from everstaff.memory.mem0_client import Mem0Client
        assert Mem0Client._parse_embedding_model("huggingface/all-MiniLM-L6-v2") == ("huggingface", "all-MiniLM-L6-v2")

    def test_parse_bare_model(self):
        from everstaff.memory.mem0_client import Mem0Client
        assert Mem0Client._parse_embedding_model("text-embedding-3-small") == ("openai", "text-embedding-3-small")


@pytest.mark.asyncio
class TestMem0ClientAdd:
    async def test_add_calls_mem0_with_scope(self):
        with patch("everstaff.memory.mem0_client.Memory") as MockMemory:
            mock_instance = MagicMock()
            mock_instance.add.return_value = [{"id": "mem_1", "event": "ADD", "data": {"memory": "test"}}]
            MockMemory.from_config.return_value = mock_instance

            from everstaff.memory.mem0_client import Mem0Client
            config = MemoryConfig(enabled=True)
            client = Mem0Client(config, "openai/gpt-4.1-nano", "text-embedding-3-small")

            messages = [{"role": "user", "content": "I like Python"}]
            result = await client.add(messages, user_id="u1", agent_id="a1")

            mock_instance.add.assert_called_once_with(messages, user_id="u1", agent_id="a1")
            assert len(result) == 1


@pytest.mark.asyncio
class TestMem0ClientSearch:
    async def test_search_filters_by_threshold(self):
        with patch("everstaff.memory.mem0_client.Memory") as MockMemory:
            mock_instance = MagicMock()
            mock_instance.search.return_value = {"results": [
                {"memory": "high relevance", "score": 0.9},
                {"memory": "low relevance", "score": 0.1},
            ]}
            MockMemory.from_config.return_value = mock_instance

            from everstaff.memory.mem0_client import Mem0Client
            config = MemoryConfig(enabled=True, search_threshold=0.3)
            client = Mem0Client(config, "openai/gpt-4.1-nano", "text-embedding-3-small")

            results = await client.search("test query", user_id="u1")

            assert len(results) == 1
            assert results[0]["memory"] == "high relevance"


class TestMem0ClientEmbedderApiKey:
    def test_api_key_passed_to_embedder_config(self):
        with patch("everstaff.memory.mem0_client.Memory") as MockMemory:
            MockMemory.from_config.return_value = MagicMock()
            from everstaff.memory.mem0_client import Mem0Client
            config = MemoryConfig(enabled=True)
            Mem0Client(config, "openai/gpt-4.1-nano", "text-embedding-3-small",
                       embedder_api_key="sk-test")
            call_args = MockMemory.from_config.call_args[0][0]
            assert call_args["embedder"]["config"]["api_key"] == "sk-test"

    def test_no_api_key_omits_field(self):
        with patch("everstaff.memory.mem0_client.Memory") as MockMemory:
            MockMemory.from_config.return_value = MagicMock()
            from everstaff.memory.mem0_client import Mem0Client
            config = MemoryConfig(enabled=True)
            Mem0Client(config, "openai/gpt-4.1-nano", "text-embedding-3-small")
            call_args = MockMemory.from_config.call_args[0][0]
            assert "api_key" not in call_args["embedder"]["config"]

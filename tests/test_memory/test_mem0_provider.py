"""Tests for Mem0Provider — PromptInjector for memory retrieval."""
import pytest
from unittest.mock import AsyncMock


@pytest.mark.asyncio
class TestMem0Provider:
    async def test_injection_empty_when_no_query(self):
        from everstaff.memory.mem0_provider import Mem0Provider
        mock_client = AsyncMock()
        provider = Mem0Provider(mock_client, user_id="u1")
        assert provider.get_prompt_injection() == ""

    async def test_refresh_populates_cache(self):
        from everstaff.memory.mem0_provider import Mem0Provider
        mock_client = AsyncMock()
        mock_client.search = AsyncMock(return_value=[
            {"memory": "User prefers Python"},
            {"memory": "User works at Acme Corp"},
        ])

        provider = Mem0Provider(mock_client, user_id="u1", agent_id="a1")
        provider.set_query("What language do I use?")
        await provider.refresh()

        injection = provider.get_prompt_injection()
        assert "[Long-term memory]" in injection
        assert "User prefers Python" in injection
        assert "User works at Acme Corp" in injection

        mock_client.search.assert_called_once_with(
            "What language do I use?",
            user_id="u1",
            agent_id="a1",
        )

    async def test_refresh_empty_results(self):
        from everstaff.memory.mem0_provider import Mem0Provider
        mock_client = AsyncMock()
        mock_client.search = AsyncMock(return_value=[])

        provider = Mem0Provider(mock_client, user_id="u1")
        provider.set_query("something")
        await provider.refresh()

        assert provider.get_prompt_injection() == ""

    async def test_refresh_failure_returns_empty(self):
        from everstaff.memory.mem0_provider import Mem0Provider
        mock_client = AsyncMock()
        mock_client.search = AsyncMock(side_effect=Exception("network error"))

        provider = Mem0Provider(mock_client, user_id="u1")
        provider.set_query("query")
        await provider.refresh()

        assert provider.get_prompt_injection() == ""

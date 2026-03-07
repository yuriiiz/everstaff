"""Tests for ProxyMem0Client."""
import pytest
from unittest.mock import AsyncMock, MagicMock


class TestProxyMem0ClientSearch:
    @pytest.mark.asyncio
    async def test_search_forwards_over_ipc(self):
        from everstaff.sandbox.proxy.mem0_client import ProxyMem0Client
        channel = MagicMock()
        channel.send_request = AsyncMock(return_value=[
            {"memory": "likes python", "score": 0.9},
        ])
        client = ProxyMem0Client(channel)
        results = await client.search("what do they like", user_id="u1", agent_id="a1")
        channel.send_request.assert_called_once_with("mem0.search", {
            "query": "what do they like",
            "top_k": None,
            "user_id": "u1",
            "agent_id": "a1",
        })
        assert results == [{"memory": "likes python", "score": 0.9}]

    @pytest.mark.asyncio
    async def test_search_with_top_k(self):
        from everstaff.sandbox.proxy.mem0_client import ProxyMem0Client
        channel = MagicMock()
        channel.send_request = AsyncMock(return_value=[])
        client = ProxyMem0Client(channel)
        await client.search("q", top_k=5, user_id="u1")
        call_params = channel.send_request.call_args[0][1]
        assert call_params["top_k"] == 5


class TestProxyMem0ClientAdd:
    @pytest.mark.asyncio
    async def test_add_forwards_over_ipc(self):
        from everstaff.sandbox.proxy.mem0_client import ProxyMem0Client
        channel = MagicMock()
        channel.send_request = AsyncMock(return_value={"results": []})
        client = ProxyMem0Client(channel)
        messages = [{"role": "user", "content": "I like Python"}]
        result = await client.add(messages, user_id="u1", agent_id="a1", run_id="s1")
        channel.send_request.assert_called_once_with("mem0.add", {
            "messages": messages,
            "user_id": "u1",
            "agent_id": "a1",
            "run_id": "s1",
        })
        assert result == {"results": []}

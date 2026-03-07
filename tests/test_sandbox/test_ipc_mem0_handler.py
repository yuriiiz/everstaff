"""Tests for IPC mem0 handler routes."""
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def mem0_client():
    client = MagicMock()
    client.add = AsyncMock(return_value={"results": [{"id": "m1", "event": "ADD"}]})
    client.search = AsyncMock(return_value=[{"memory": "likes python", "score": 0.9}])
    return client


@pytest.fixture
def handler(mem0_client):
    from everstaff.sandbox.ipc.server_handler import IpcServerHandler
    from everstaff.sandbox.token_store import EphemeralTokenStore
    from everstaff.core.secret_store import SecretStore
    h = IpcServerHandler(
        token_store=EphemeralTokenStore(),
        secret_store=SecretStore({}),
        mem0_client=mem0_client,
    )
    return h


class TestMem0Add:
    @pytest.mark.asyncio
    async def test_routes_to_mem0_add(self, handler, mem0_client):
        result = await handler.handle("mem0.add", {
            "messages": [{"role": "user", "content": "I like Python"}],
            "user_id": "u1",
            "agent_id": "a1",
            "run_id": "s1",
        })
        mem0_client.add.assert_called_once_with(
            [{"role": "user", "content": "I like Python"}],
            user_id="u1", agent_id="a1", run_id="s1",
        )
        assert result == {"results": [{"id": "m1", "event": "ADD"}]}


class TestMem0Search:
    @pytest.mark.asyncio
    async def test_routes_to_mem0_search(self, handler, mem0_client):
        result = await handler.handle("mem0.search", {
            "query": "what do they like",
            "top_k": 5,
            "user_id": "u1",
        })
        mem0_client.search.assert_called_once_with(
            "what do they like", top_k=5, user_id="u1",
        )
        assert result == [{"memory": "likes python", "score": 0.9}]

    @pytest.mark.asyncio
    async def test_search_without_mem0_returns_empty(self):
        from everstaff.sandbox.ipc.server_handler import IpcServerHandler
        from everstaff.sandbox.token_store import EphemeralTokenStore
        from everstaff.core.secret_store import SecretStore
        h = IpcServerHandler(
            token_store=EphemeralTokenStore(),
            secret_store=SecretStore({}),
        )
        result = await h.handle("mem0.search", {"query": "test", "user_id": "u1"})
        assert result == []

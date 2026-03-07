"""Tests for the memories API endpoints."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient

from everstaff.api.memories import make_router


def _make_app(mem0_client=None):
    """Build a minimal FastAPI app with the memories router."""
    app = FastAPI()
    app.state.mem0_client = mem0_client
    app.include_router(make_router(), prefix="/api")
    return app


def _mock_client():
    client = AsyncMock()
    client.get_all.return_value = []
    client.search.return_value = []
    return client


def _auth_middleware(user_id):
    """Return a middleware that sets request.state.user."""
    async def middleware(request, call_next):
        from everstaff.api.auth.models import UserIdentity
        request.state.user = UserIdentity(user_id=user_id, provider="test")
        return await call_next(request)
    return middleware


class TestListUserMemories:
    def test_merges_user_and_default(self):
        client = _mock_client()
        client.get_all.side_effect = [
            [{"id": "m1", "memory": "personal", "user_id": "alice"}],
            [{"id": "m2", "memory": "shared", "user_id": "default"}],
        ]
        app = _make_app(client)
        app.middleware("http")(_auth_middleware("alice"))
        tc = TestClient(app)
        resp = tc.get("/api/memories")
        assert resp.status_code == 200
        assert len(resp.json()["memories"]) == 2

    def test_deduplicates_by_id(self):
        client = _mock_client()
        client.get_all.side_effect = [
            [{"id": "m1", "memory": "same", "user_id": "alice"}],
            [{"id": "m1", "memory": "same", "user_id": "default"}],
        ]
        app = _make_app(client)
        app.middleware("http")(_auth_middleware("alice"))
        tc = TestClient(app)
        resp = tc.get("/api/memories")
        assert len(resp.json()["memories"]) == 1

    def test_no_auth_uses_default(self):
        client = _mock_client()
        client.get_all.return_value = [{"id": "m1", "memory": "shared", "user_id": "default"}]
        app = _make_app(client)
        tc = TestClient(app)
        resp = tc.get("/api/memories")
        assert resp.status_code == 200
        # Only one call (user_id == default, no need for two)
        client.get_all.assert_called_once()

    def test_memory_disabled_returns_empty(self):
        app = _make_app(mem0_client=None)
        tc = TestClient(app)
        resp = tc.get("/api/memories")
        assert resp.status_code == 200
        assert resp.json()["memories"] == []

    def test_limit_param(self):
        client = _mock_client()
        client.get_all.side_effect = [[], []]
        app = _make_app(client)
        app.middleware("http")(_auth_middleware("alice"))
        tc = TestClient(app)
        tc.get("/api/memories?limit=25")
        for call in client.get_all.call_args_list:
            assert call.kwargs["limit"] == 25


class TestSearchUserMemories:
    def test_search_merges_user_and_default(self):
        client = _mock_client()
        client.search.side_effect = [
            [{"id": "m1", "memory": "personal", "score": 0.9, "user_id": "alice"}],
            [{"id": "m2", "memory": "shared", "score": 0.7, "user_id": "default"}],
        ]
        app = _make_app(client)
        app.middleware("http")(_auth_middleware("alice"))
        tc = TestClient(app)
        resp = tc.get("/api/memories/search?q=test")
        assert resp.status_code == 200
        assert len(resp.json()["memories"]) == 2

    def test_search_dedup_keeps_higher_score(self):
        client = _mock_client()
        client.search.side_effect = [
            [{"id": "m1", "memory": "same", "score": 0.6, "user_id": "alice"}],
            [{"id": "m1", "memory": "same", "score": 0.9, "user_id": "default"}],
        ]
        app = _make_app(client)
        app.middleware("http")(_auth_middleware("alice"))
        tc = TestClient(app)
        resp = tc.get("/api/memories/search?q=test")
        memories = resp.json()["memories"]
        assert len(memories) == 1
        assert memories[0]["score"] == 0.9

    def test_search_requires_q_param(self):
        app = _make_app(_mock_client())
        tc = TestClient(app)
        resp = tc.get("/api/memories/search")
        assert resp.status_code == 422


class TestAgentMemories:
    def test_list_passes_agent_id(self):
        client = _mock_client()
        client.get_all.side_effect = [
            [{"id": "m1", "memory": "agent mem", "agent_id": "agent-1", "user_id": "alice"}],
            [],
        ]
        app = _make_app(client)
        app.middleware("http")(_auth_middleware("alice"))
        tc = TestClient(app)
        resp = tc.get("/api/agents/agent-1/memories")
        assert resp.status_code == 200
        for call in client.get_all.call_args_list:
            assert call.kwargs["agent_id"] == "agent-1"

    def test_search_passes_agent_id(self):
        client = _mock_client()
        client.search.side_effect = [
            [{"id": "m1", "memory": "found", "score": 0.8, "agent_id": "agent-1", "user_id": "alice"}],
            [],
        ]
        app = _make_app(client)
        app.middleware("http")(_auth_middleware("alice"))
        tc = TestClient(app)
        resp = tc.get("/api/agents/agent-1/memories/search?q=test")
        assert resp.status_code == 200
        for call in client.search.call_args_list:
            assert call.args[0] == "test"
            assert call.kwargs["agent_id"] == "agent-1"

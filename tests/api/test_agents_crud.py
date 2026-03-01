# tests/api/test_agents_crud.py
import pytest
from pathlib import Path
from httpx import AsyncClient, ASGITransport
from api import create_app


def _make_app(tmp_path):
    from everstaff.core.config import load_config
    config = load_config()
    config = config.model_copy(update={
        "agents_dir": str(tmp_path / "agents"),
        "sessions_dir": str(tmp_path / "sessions"),
    })
    (tmp_path / "agents").mkdir()
    (tmp_path / "sessions").mkdir()
    return create_app(config=config, sessions_dir=str(tmp_path / "sessions"))


@pytest.mark.asyncio
async def test_create_agent(tmp_path):
    app = _make_app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/api/agents", json={"agent_name": "test-agent", "uuid": "abc-123"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "test-agent"
    assert (tmp_path / "agents" / "test-agent.yaml").exists()


@pytest.mark.asyncio
async def test_update_agent(tmp_path):
    app = _make_app(tmp_path)
    (tmp_path / "agents" / "test-agent.yaml").write_text("agent_name: test-agent\n")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.put("/api/agents/test-agent", json={"agent_name": "test-agent", "uuid": "new-uuid"})
    assert resp.status_code == 200
    assert resp.json()["updated"] is True


@pytest.mark.asyncio
async def test_delete_agent(tmp_path):
    app = _make_app(tmp_path)
    (tmp_path / "agents" / "test-agent.yaml").write_text("agent_name: test-agent\n")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.delete("/api/agents/test-agent")
    assert resp.status_code == 204
    assert not (tmp_path / "agents" / "test-agent.yaml").exists()


@pytest.mark.asyncio
async def test_create_agent_conflict(tmp_path):
    app = _make_app(tmp_path)
    (tmp_path / "agents" / "test-agent.yaml").write_text("agent_name: test-agent\n")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/api/agents", json={"agent_name": "test-agent"})
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_delete_agent_not_found(tmp_path):
    app = _make_app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.delete("/api/agents/nonexistent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_agent_not_found(tmp_path):
    app = _make_app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.put("/api/agents/ghost", json={"agent_name": "ghost"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_agent_missing_name(tmp_path):
    app = _make_app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/api/agents", json={"uuid": "abc-123"})
    assert resp.status_code == 400

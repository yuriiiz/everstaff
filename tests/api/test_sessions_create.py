# tests/api/test_sessions_create.py
import pytest
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient, ASGITransport
from api import create_app


def _make_app(tmp_path, agents_dir=None):
    from everstaff.core.config import load_config
    config = load_config()
    updates = {"sessions_dir": str(tmp_path / "sessions")}
    if agents_dir:
        updates["agents_dir"] = str(agents_dir)
    config = config.model_copy(update=updates)
    (tmp_path / "sessions").mkdir(exist_ok=True)
    return create_app(config=config, sessions_dir=str(tmp_path / "sessions"))


@pytest.mark.asyncio
async def test_create_session_returns_202(tmp_path):
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    (agents_dir / "myagent.yaml").write_text(
        "agent_name: myagent\nuuid: test-uuid\n", encoding="utf-8"
    )
    app = _make_app(tmp_path, agents_dir=agents_dir)

    with patch("everstaff.api.sessions._resume_session_task", new_callable=AsyncMock):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/sessions", json={"agent_name": "myagent", "user_input": "hello"})

    assert resp.status_code == 202
    body = resp.json()
    assert "session_id" in body
    assert body["status"] == "running"


@pytest.mark.asyncio
async def test_create_session_default_empty_input(tmp_path):
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    (agents_dir / "myagent.yaml").write_text("agent_name: myagent\n", encoding="utf-8")
    app = _make_app(tmp_path, agents_dir=agents_dir)

    with patch("everstaff.api.sessions._resume_session_task", new_callable=AsyncMock):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/sessions", json={"agent_name": "myagent"})

    assert resp.status_code == 202
    assert "session_id" in resp.json()


@pytest.mark.asyncio
async def test_create_session_unknown_agent(tmp_path):
    app = _make_app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/api/sessions", json={"agent_name": "ghost", "user_input": ""})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_session_missing_agent_name(tmp_path):
    app = _make_app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/api/sessions", json={"user_input": "hi"})
    assert resp.status_code == 422  # Pydantic validation error

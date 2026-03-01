import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def make_app():
    from everstaff.api import create_app
    return create_app()


def test_sessions_list_returns_list():
    app = make_app()
    client = TestClient(app)
    resp = client.get("/api/sessions")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_sessions_stop_unknown_session():
    app = make_app()
    client = TestClient(app)
    resp = client.post("/api/sessions/nonexistent-id/stop")
    assert resp.status_code == 404


def test_agents_list_returns_list():
    app = make_app()
    client = TestClient(app)
    resp = client.get("/api/agents")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ---------------------------------------------------------------------------
# New tests for Task 9
# ---------------------------------------------------------------------------

def _write_session(sessions_dir: Path, session_id: str, status: str = "completed") -> None:
    """Helper to create a minimal session.json for testing."""
    from datetime import datetime, timezone
    d = sessions_dir / session_id
    d.mkdir(parents=True, exist_ok=True)
    updated = datetime.now(timezone.utc).isoformat()
    (d / "session.json").write_text(json.dumps({
        "session_id": session_id,
        "agent_name": "test-agent",
        "parent_session_id": None,
        "created_at": updated,
        "updated_at": updated,
        "status": status,
        "metadata": {},
        "messages": [],
    }))


@pytest.fixture
def tmp_path_sessions(tmp_path):
    return tmp_path / "sessions"


@pytest.fixture
def client(tmp_path_sessions):
    tmp_path_sessions.mkdir(parents=True, exist_ok=True)
    from everstaff.api import create_app
    app = create_app(sessions_dir=str(tmp_path_sessions))
    from fastapi.testclient import TestClient
    return TestClient(app)


def test_list_sessions_filter_by_status(client, tmp_path_sessions):
    """GET /sessions?status=waiting_for_human returns only matching sessions."""
    _write_session(tmp_path_sessions, "sess-a", status="waiting_for_human")
    _write_session(tmp_path_sessions, "sess-b", status="completed")

    resp = client.get("/api/sessions?status=waiting_for_human")
    assert resp.status_code == 200
    ids = [s["session_id"] for s in resp.json()]
    assert "sess-a" in ids
    assert "sess-b" not in ids


def test_list_sessions_no_filter_returns_all(client, tmp_path_sessions):
    """GET /sessions without filter returns all sessions."""
    _write_session(tmp_path_sessions, "sess-x", status="completed")
    _write_session(tmp_path_sessions, "sess-y", status="failed")

    resp = client.get("/api/sessions")
    assert resp.status_code == 200
    ids = [s["session_id"] for s in resp.json()]
    assert "sess-x" in ids
    assert "sess-y" in ids


def test_resume_cancelled_session(client, tmp_path_sessions):
    """POST /sessions/{id}/resume works for cancelled sessions (no hitl.json needed)."""
    _write_session(tmp_path_sessions, "sess-cancelled", status="cancelled")

    resp = client.post("/api/sessions/sess-cancelled/resume", json={"user_input": "continue"})
    assert resp.status_code == 202


def test_resume_interrupted_session(client, tmp_path_sessions):
    """POST /sessions/{id}/resume works for stale running sessions (interrupted)."""
    from datetime import datetime, timezone, timedelta
    import json

    # Create a "running" session with a stale updated_at (>5 min ago)
    session_id = "sess-stale"
    d = tmp_path_sessions / session_id
    d.mkdir(parents=True, exist_ok=True)
    stale_time = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    (d / "session.json").write_text(json.dumps({
        "session_id": session_id,
        "agent_name": "test-agent",
        "parent_session_id": None,
        "created_at": stale_time,
        "updated_at": stale_time,
        "status": "running",  # stored as running, but stale
        "metadata": {},
        "messages": [],
    }))

    resp = client.post(f"/api/sessions/{session_id}/resume", json={"user_input": "continue"})
    assert resp.status_code == 202, f"Expected 202, got {resp.status_code}: {resp.json()}"


@pytest.mark.asyncio
async def test_resume_session_task_calls_ctx_aclose_on_success(tmp_path):
    """_resume_session_task must call ctx.aclose() after runtime.run() succeeds."""
    from unittest.mock import AsyncMock, patch, MagicMock
    import everstaff.api.sessions as sessions_mod

    mock_ctx = AsyncMock()
    mock_runtime = AsyncMock()
    mock_runtime.run = AsyncMock(return_value="done")

    mock_builder_instance = MagicMock()
    mock_builder_instance.build = AsyncMock(return_value=(mock_runtime, mock_ctx))
    mock_builder_cls = MagicMock(return_value=mock_builder_instance)

    with patch("everstaff.builder.agent_builder.AgentBuilder", mock_builder_cls), \
         patch("everstaff.utils.yaml_loader.load_yaml", return_value={}), \
         patch("everstaff.schema.agent_spec.AgentSpec", return_value=MagicMock()):

        config = MagicMock()
        config.sessions_dir = str(tmp_path)
        config.agents_dir = str(tmp_path)
        (tmp_path / "test_agent.yaml").write_text("")

        await sessions_mod._resume_session_task(
            session_id="sess1",
            agent_name="test_agent",
            decision_text="approved",
            config=config,
        )

    mock_ctx.aclose.assert_called_once()


@pytest.mark.asyncio
async def test_resume_session_task_calls_ctx_aclose_on_failure(tmp_path):
    """_resume_session_task must call ctx.aclose() even when runtime.run() raises."""
    from unittest.mock import AsyncMock, patch, MagicMock
    import everstaff.api.sessions as sessions_mod

    mock_ctx = AsyncMock()
    mock_runtime = AsyncMock()
    mock_runtime.run = AsyncMock(side_effect=RuntimeError("boom"))

    mock_builder_instance = MagicMock()
    mock_builder_instance.build = AsyncMock(return_value=(mock_runtime, mock_ctx))
    mock_builder_cls = MagicMock(return_value=mock_builder_instance)

    with patch("everstaff.builder.agent_builder.AgentBuilder", mock_builder_cls), \
         patch("everstaff.utils.yaml_loader.load_yaml", return_value={}), \
         patch("everstaff.schema.agent_spec.AgentSpec", return_value=MagicMock()):

        config = MagicMock()
        config.sessions_dir = str(tmp_path)
        config.agents_dir = str(tmp_path)
        (tmp_path / "test_agent.yaml").write_text("")

        await sessions_mod._resume_session_task(
            session_id="sess1",
            agent_name="test_agent",
            decision_text="approved",
            config=config,
        )

    mock_ctx.aclose.assert_called_once()


@pytest.mark.asyncio
async def test_start_session_passes_broadcast_fn(monkeypatch, tmp_path):
    """start_session must pass broadcast_fn to _resume_session_task so WS events are pushed."""
    captured = {}

    async def fake_resume(*args, **kwargs):
        captured["broadcast_fn"] = kwargs.get("broadcast_fn")

    monkeypatch.setattr("everstaff.api.sessions._resume_session_task", fake_resume)

    # create a minimal agent yaml so the route doesn't 404
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    (agents_dir / "test.yaml").write_text("agent_name: test\nmodel: fast\n")

    from everstaff.core.config import load_config
    from everstaff.api import create_app
    config = load_config()
    config = config.model_copy(update={
        "agents_dir": str(agents_dir),
        "sessions_dir": str(tmp_path / "sessions"),
    })

    app = create_app(config=config)
    from httpx import AsyncClient, ASGITransport
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/sessions", json={"agent_name": "test", "user_input": "hi"})
    assert resp.status_code == 202
    assert captured.get("broadcast_fn") is not None

import json
import pytest
from datetime import datetime, timezone
from unittest.mock import patch


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_session_with_hitl(session_id, hitl_id, agent_name="test-agent"):
    now = _now()
    return {
        "session_id": session_id,
        "agent_name": agent_name,
        "created_at": now,
        "updated_at": now,
        "status": "waiting_for_human",
        "metadata": {},
        "messages": [],
        "hitl_requests": [
            {
                "hitl_id": hitl_id,
                "tool_call_id": "call-1",
                "created_at": now,
                "timeout_seconds": 86400,
                "status": "pending",
                "origin_session_id": session_id,
                "origin_agent_name": agent_name,
                "request": {
                    "type": "approve_reject",
                    "prompt": "Proceed?",
                    "options": [],
                    "context": "",
                },
                "response": None,
            }
        ],
    }


def test_list_pending_hitl_from_session_json(tmp_path):
    """GET /hitl must read hitl_requests from session.json, not hitl.json."""
    from fastapi.testclient import TestClient
    from everstaff.api import create_app

    sessions_dir = tmp_path / "sessions"
    sid = "sess-1"
    (sessions_dir / sid).mkdir(parents=True)
    session_data = make_session_with_hitl(sid, "hitl-abc")
    (sessions_dir / sid / "session.json").write_text(json.dumps(session_data))

    app = create_app(sessions_dir=str(sessions_dir))
    client = TestClient(app)
    resp = client.get("/api/hitl")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["hitl_id"] == "hitl-abc"


def test_resolve_hitl_updates_session_json(tmp_path):
    """POST /hitl/{id}/resolve must update hitl_requests in session.json."""
    from fastapi.testclient import TestClient
    from everstaff.api import create_app

    sessions_dir = tmp_path / "sessions"
    sid = "sess-2"
    (sessions_dir / sid).mkdir(parents=True)
    session_data = make_session_with_hitl(sid, "hitl-xyz")
    (sessions_dir / sid / "session.json").write_text(json.dumps(session_data))

    app = create_app(sessions_dir=str(sessions_dir))

    resumed = []
    async def fake_resume(*args, **kwargs):
        resumed.append(args[0])

    with patch("everstaff.api.sessions._resume_session_task", fake_resume):
        client = TestClient(app)
        resp = client.post(
            "/api/hitl/hitl-xyz/resolve",
            json={"decision": "approved"},
        )

    assert resp.status_code == 200
    # Verify session.json was updated
    updated = json.loads((sessions_dir / sid / "session.json").read_text())
    assert updated["hitl_requests"][0]["status"] == "resolved"
    # All settled → resume triggered
    assert sid in resumed


def test_resolve_waits_when_not_all_settled(tmp_path):
    """When session has 2 HITLs and only 1 resolved, must NOT trigger resume."""
    from fastapi.testclient import TestClient
    from everstaff.api import create_app

    sessions_dir = tmp_path / "sessions"
    sid = "sess-3"
    (sessions_dir / sid).mkdir(parents=True)
    session_data = make_session_with_hitl(sid, "hitl-1")
    session_data["hitl_requests"].append({
        "hitl_id": "hitl-2",
        "tool_call_id": "call-2",
        "created_at": _now(),
        "timeout_seconds": 86400,
        "status": "pending",
        "origin_session_id": sid,
        "origin_agent_name": "test-agent",
        "request": {"type": "provide_input", "prompt": "Q2", "options": [], "context": ""},
        "response": None,
    })
    (sessions_dir / sid / "session.json").write_text(json.dumps(session_data))

    app = create_app(sessions_dir=str(sessions_dir))

    resumed = []
    async def fake_resume(*args, **kwargs):
        resumed.append(args[0])

    with patch("everstaff.api.sessions._resume_session_task", fake_resume):
        client = TestClient(app)
        resp = client.post("/api/hitl/hitl-1/resolve", json={"decision": "yes"})

    assert resp.status_code == 200
    assert resumed == []  # NOT resumed yet — hitl-2 still pending

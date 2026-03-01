"""Tests for HITL timeout detection."""
import json
from datetime import datetime, timezone, timedelta
from unittest.mock import patch


def test_expired_hitl_detected_on_list(tmp_path):
    """GET /hitl must not return timed-out requests."""
    from fastapi.testclient import TestClient
    from everstaff.api import create_app

    sessions_dir = tmp_path / "sessions"
    sid = "sess-exp"
    (sessions_dir / sid).mkdir(parents=True)

    past = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    session_data = {
        "session_id": sid,
        "agent_name": "test",
        "created_at": past,
        "updated_at": past,
        "status": "waiting_for_human",
        "metadata": {},
        "messages": [],
        "hitl_requests": [{
            "hitl_id": "hitl-old",
            "tool_call_id": "c1",
            "created_at": past,
            "timeout_seconds": 3600,  # 1 hour — long expired
            "status": "pending",
            "origin_session_id": sid,
            "origin_agent_name": "test",
            "request": {"type": "approve_reject", "prompt": "Q", "options": [], "context": ""},
            "response": None,
        }],
    }
    (sessions_dir / sid / "session.json").write_text(json.dumps(session_data))

    app = create_app(sessions_dir=str(sessions_dir))
    client = TestClient(app)
    resp = client.get("/api/hitl")
    # Expired HITL should not appear in pending list
    assert resp.status_code == 200
    assert len(resp.json()) == 0


def test_resolve_rejects_expired_hitl(tmp_path):
    """POST /hitl/{id}/resolve must reject if request has expired."""
    from fastapi.testclient import TestClient
    from everstaff.api import create_app

    sessions_dir = tmp_path / "sessions"
    sid = "sess-exp2"
    (sessions_dir / sid).mkdir(parents=True)

    past = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    session_data = {
        "session_id": sid,
        "agent_name": "test",
        "created_at": past,
        "updated_at": past,
        "status": "waiting_for_human",
        "metadata": {},
        "messages": [],
        "hitl_requests": [{
            "hitl_id": "hitl-expired",
            "tool_call_id": "c1",
            "created_at": past,
            "timeout_seconds": 3600,
            "status": "pending",
            "origin_session_id": sid,
            "origin_agent_name": "test",
            "request": {"type": "approve_reject", "prompt": "Q", "options": [], "context": ""},
            "response": None,
        }],
    }
    (sessions_dir / sid / "session.json").write_text(json.dumps(session_data))

    app = create_app(sessions_dir=str(sessions_dir))
    client = TestClient(app)
    resp = client.post("/api/hitl/hitl-expired/resolve", json={"decision": "yes"})
    assert resp.status_code == 410  # Gone


def test_non_expired_hitl_is_listed(tmp_path):
    """GET /hitl must return fresh (non-expired) HITL requests."""
    from fastapi.testclient import TestClient
    from everstaff.api import create_app

    sessions_dir = tmp_path / "sessions"
    sid = "sess-fresh"
    (sessions_dir / sid).mkdir(parents=True)

    now = datetime.now(timezone.utc).isoformat()
    session_data = {
        "session_id": sid,
        "agent_name": "test",
        "created_at": now,
        "updated_at": now,
        "status": "waiting_for_human",
        "metadata": {},
        "messages": [],
        "hitl_requests": [{
            "hitl_id": "hitl-fresh",
            "tool_call_id": "c1",
            "created_at": now,
            "timeout_seconds": 86400,
            "status": "pending",
            "origin_session_id": sid,
            "origin_agent_name": "test",
            "request": {"type": "approve_reject", "prompt": "Fresh Q", "options": [], "context": ""},
            "response": None,
        }],
    }
    (sessions_dir / sid / "session.json").write_text(json.dumps(session_data))

    app = create_app(sessions_dir=str(sessions_dir))
    client = TestClient(app)
    resp = client.get("/api/hitl")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["hitl_id"] == "hitl-fresh"


def test_zero_timeout_never_expires(tmp_path):
    """timeout_seconds=0 means no timeout — request should always be listed."""
    from fastapi.testclient import TestClient
    from everstaff.api import create_app

    sessions_dir = tmp_path / "sessions"
    sid = "sess-no-timeout"
    (sessions_dir / sid).mkdir(parents=True)

    past = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()
    session_data = {
        "session_id": sid,
        "agent_name": "test",
        "created_at": past,
        "updated_at": past,
        "status": "waiting_for_human",
        "metadata": {},
        "messages": [],
        "hitl_requests": [{
            "hitl_id": "hitl-no-timeout",
            "tool_call_id": "c1",
            "created_at": past,
            "timeout_seconds": 0,  # no timeout
            "status": "pending",
            "origin_session_id": sid,
            "origin_agent_name": "test",
            "request": {"type": "approve_reject", "prompt": "Old Q", "options": [], "context": ""},
            "response": None,
        }],
    }
    (sessions_dir / sid / "session.json").write_text(json.dumps(session_data))

    app = create_app(sessions_dir=str(sessions_dir))
    client = TestClient(app)
    resp = client.get("/api/hitl")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["hitl_id"] == "hitl-no-timeout"

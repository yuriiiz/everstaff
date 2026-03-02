"""Test HITL resolution with grant_scope for tool_permission requests."""
import json
import os
import pytest
from datetime import datetime, timezone


@pytest.fixture
def session_with_tool_permission(tmp_path):
    """Create a session dir with a tool_permission HITL request using sync I/O."""
    session_id = "test-session"
    session_dir = tmp_path / session_id
    session_dir.mkdir()
    data = {
        "session_id": session_id,
        "agent_name": "TestAgent",
        "status": "waiting_for_human",
        "hitl_requests": [{
            "hitl_id": "hitl-001",
            "tool_call_id": "tc-42",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "timeout_seconds": 86400,
            "status": "pending",
            "request": {
                "type": "tool_permission",
                "prompt": "Agent wants to execute 'Bash'",
                "tool_name": "Bash",
                "tool_args": {"command": "git status"},
            },
        }],
    }
    (session_dir / "session.json").write_text(json.dumps(data))

    from everstaff.storage.local import LocalFileStore
    store = LocalFileStore(str(tmp_path))
    return session_id, store


@pytest.mark.asyncio
async def test_resolve_tool_permission_with_grant_scope(session_with_tool_permission):
    session_id, store = session_with_tool_permission

    from everstaff.hitl.resolve import resolve_hitl
    resolution = await resolve_hitl(
        session_id=session_id,
        hitl_id="hitl-001",
        decision="approved",
        grant_scope="session",
        file_store=store,
    )
    assert resolution.decision == "approved"
    assert resolution.grant_scope == "session"

    raw = await store.read(f"{session_id}/session.json")
    data = json.loads(raw.decode())
    resp = data["hitl_requests"][0]["response"]
    assert resp["grant_scope"] == "session"


@pytest.mark.asyncio
async def test_resolve_without_grant_scope(session_with_tool_permission):
    session_id, store = session_with_tool_permission

    from everstaff.hitl.resolve import resolve_hitl
    resolution = await resolve_hitl(
        session_id=session_id,
        hitl_id="hitl-001",
        decision="rejected",
        file_store=store,
    )
    assert resolution.decision == "rejected"
    assert resolution.grant_scope is None

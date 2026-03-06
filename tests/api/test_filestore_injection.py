# tests/api/test_filestore_injection.py
import pytest
from everstaff.api import create_app
from everstaff.protocols import FileStore


def test_app_has_file_store(tmp_path):
    """API app must expose file_store on app.state for route handlers."""
    app = create_app(sessions_dir=str(tmp_path))
    assert hasattr(app.state, "file_store"), "app.state.file_store must be set"
    assert isinstance(app.state.file_store, FileStore), "file_store must implement FileStore protocol"


@pytest.mark.asyncio
async def test_hitl_list_via_filestore(tmp_path):
    """HITL list endpoint must read from session.json hitl_requests (not hitl.json)."""
    import json
    from datetime import datetime, timezone
    from httpx import AsyncClient, ASGITransport

    # Create a fake pending HITL request embedded in session.json
    app = create_app(sessions_dir=str(tmp_path))
    store = app.state.file_store

    now = datetime.now(timezone.utc).isoformat()
    session_data = {
        "session_id": "test-s1",
        "agent_name": "test-agent",
        "created_at": now,
        "updated_at": now,
        "status": "waiting_for_human",
        "metadata": {},
        "messages": [],
        "hitl_requests": [{
            "hitl_id": "test-h1",
            "tool_call_id": "c1",
            "created_at": now,
            "timeout_seconds": 86400,
            "status": "pending",
            "origin_session_id": "test-s1",
            "origin_agent_name": "test-agent",
            "request": {"type": "approve_reject", "prompt": "Allow?", "options": [], "context": ""},
            "response": None,
        }],
    }
    await store.write("test-s1/session.json", json.dumps(session_data).encode())

    # Register in session index so the HITL fast-path can find it
    index = getattr(app.state, "session_index", None)
    if index is not None:
        from everstaff.session.index import IndexEntry
        index.upsert(IndexEntry(
            id="test-s1", root="test-s1", parent=None,
            agent="test-agent", agent_uuid=None,
            status="waiting_for_human", created_at=now, updated_at=now,
        ))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/hitl")

    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["hitl_id"] == "test-h1"

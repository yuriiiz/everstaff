"""Canonical resolve_hitl function — validates, updates session.json, returns resolution."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timezone


@pytest.fixture
def mock_file_store():
    store = MagicMock()
    session_data = {
        "session_id": "sess-1",
        "agent_name": "test-agent",
        "status": "waiting_for_human",
        "hitl_requests": [
            {
                "hitl_id": "h-1",
                "status": "pending",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "timeout_seconds": 86400,
                "tool_call_id": "tc-1",
                "request": {"type": "approve_reject", "prompt": "OK?"},
                "response": None,
            }
        ],
        "messages": [],
    }
    raw = json.dumps(session_data).encode()
    store.read = AsyncMock(return_value=raw)
    store.write = AsyncMock()
    store.exists = AsyncMock(return_value=True)
    return store


@pytest.mark.asyncio
async def test_resolve_hitl_marks_resolved(mock_file_store):
    from everstaff.hitl.resolve import resolve_hitl

    result = await resolve_hitl(
        session_id="sess-1",
        hitl_id="h-1",
        decision="approved",
        file_store=mock_file_store,
    )
    assert result.decision == "approved"
    # Verify write was called
    mock_file_store.write.assert_called_once()
    written = json.loads(mock_file_store.write.call_args[0][1].decode())
    hitl = written["hitl_requests"][0]
    assert hitl["status"] == "resolved"
    assert hitl["response"]["decision"] == "approved"


@pytest.mark.asyncio
async def test_resolve_hitl_raises_on_not_found(mock_file_store):
    from everstaff.hitl.resolve import resolve_hitl, HitlNotFoundError

    with pytest.raises(HitlNotFoundError):
        await resolve_hitl(
            session_id="sess-1",
            hitl_id="h-nonexistent",
            decision="approved",
            file_store=mock_file_store,
        )


@pytest.mark.asyncio
async def test_resolve_hitl_raises_on_already_resolved(mock_file_store):
    from everstaff.hitl.resolve import resolve_hitl, HitlAlreadyResolvedError

    # Manually mark as resolved in the mock data
    data = json.loads((await mock_file_store.read("sess-1/session.json")).decode())
    data["hitl_requests"][0]["status"] = "resolved"
    mock_file_store.read = AsyncMock(return_value=json.dumps(data).encode())

    with pytest.raises(HitlAlreadyResolvedError):
        await resolve_hitl(
            session_id="sess-1",
            hitl_id="h-1",
            decision="approved",
            file_store=mock_file_store,
        )


def test_all_hitls_settled_true():
    from everstaff.hitl.resolve import all_hitls_settled
    data = {"hitl_requests": [{"status": "resolved"}, {"status": "expired"}]}
    assert all_hitls_settled(data) is True


def test_all_hitls_settled_false():
    from everstaff.hitl.resolve import all_hitls_settled
    data = {"hitl_requests": [{"status": "resolved"}, {"status": "pending"}]}
    assert all_hitls_settled(data) is False


def test_all_hitls_settled_empty():
    from everstaff.hitl.resolve import all_hitls_settled
    assert all_hitls_settled({"hitl_requests": []}) is True
    assert all_hitls_settled({}) is True

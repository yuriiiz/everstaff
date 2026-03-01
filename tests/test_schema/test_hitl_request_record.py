"""HitlRequestRecord model for typed HITL storage."""
from datetime import datetime, timezone


def test_hitl_request_record_roundtrip():
    from everstaff.schema.hitl_models import HitlRequestRecord, HitlRequestPayload

    record = HitlRequestRecord(
        hitl_id="h-1",
        tool_call_id="tc-1",
        created_at=datetime.now(timezone.utc).isoformat(),
        timeout_seconds=3600,
        status="pending",
        origin_session_id="sess-child",
        origin_agent_name="child-agent",
        request=HitlRequestPayload(type="approve_reject", prompt="Deploy?"),
        response=None,
    )
    d = record.model_dump(mode="json")
    assert d["hitl_id"] == "h-1"
    assert d["request"]["type"] == "approve_reject"
    assert d["response"] is None

    record2 = HitlRequestRecord.model_validate(d)
    assert record2.hitl_id == record.hitl_id
    assert record2.request.prompt == "Deploy?"


def test_hitl_request_record_with_resolution():
    from everstaff.schema.hitl_models import HitlRequestRecord, HitlRequestPayload
    from everstaff.schema.api_models import HitlResolution

    record = HitlRequestRecord(
        hitl_id="h-2",
        created_at=datetime.now(timezone.utc).isoformat(),
        status="resolved",
        request=HitlRequestPayload(type="provide_input", prompt="Name?"),
        response=HitlResolution(
            decision="John",
            resolved_at=datetime.now(timezone.utc),
        ),
    )
    d = record.model_dump(mode="json")
    assert d["status"] == "resolved"
    assert d["response"]["decision"] == "John"


def test_hitl_request_record_backward_compat_with_raw_dict():
    """HitlRequestRecord must be able to parse the raw dict format used by runtime checkpoint."""
    from everstaff.schema.hitl_models import HitlRequestRecord
    raw = {
        "hitl_id": "h-3",
        "tool_call_id": "tc-3",
        "created_at": "2026-02-28T10:00:00+00:00",
        "timeout_seconds": 86400,
        "status": "pending",
        "origin_session_id": "sess-1",
        "origin_agent_name": "agent-1",
        "request": {"type": "approve_reject", "prompt": "OK?", "options": [], "context": ""},
        "response": None,
    }
    record = HitlRequestRecord.model_validate(raw)
    assert record.hitl_id == "h-3"
    assert record.request.type == "approve_reject"

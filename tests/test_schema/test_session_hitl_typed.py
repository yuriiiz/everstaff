"""Session.hitl_requests must accept HitlRequestRecord-compatible dicts."""
from datetime import datetime, timezone


def test_session_accepts_typed_hitl_records():
    from everstaff.schema.memory import Session
    from everstaff.schema.hitl_models import HitlRequestRecord, HitlRequestPayload

    record = HitlRequestRecord(
        hitl_id="h-1",
        created_at=datetime.now(timezone.utc).isoformat(),
        request=HitlRequestPayload(type="approve_reject", prompt="OK?"),
    )
    session = Session(
        session_id="s-1",
        created_at=datetime.now(timezone.utc).isoformat(),
        updated_at=datetime.now(timezone.utc).isoformat(),
        hitl_requests=[record.model_dump(mode="json")],
    )
    assert len(session.hitl_requests) == 1

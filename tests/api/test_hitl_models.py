# tests/api/test_hitl_models.py
from everstaff.schema.api_models import HitlResolution
from datetime import datetime, timezone


def test_hitl_resolution_fields():
    r = HitlResolution(
        decision="approved",
        comment="LGTM",
        resolved_at=datetime.now(timezone.utc),
        resolved_by="human",
    )
    assert r.decision == "approved"
    assert r.comment == "LGTM"
    assert r.resolved_by == "human"


def test_hitl_resolution_optional_comment():
    r = HitlResolution(
        decision="rejected",
        resolved_at=datetime.now(timezone.utc),
        resolved_by="bot",
    )
    assert r.comment is None

"""Tests for updated HITL data models."""
import pytest
from everstaff.protocols import HitlRequest, HumanApprovalRequired


def test_hitl_request_has_new_fields():
    """HitlRequest must have origin_session_id, origin_agent_name, timeout_seconds."""
    req = HitlRequest(
        hitl_id="h1",
        type="provide_input",
        prompt="Choose one",
        origin_session_id="child-123",
        origin_agent_name="Search Agent",
        timeout_seconds=3600,
    )
    assert req.origin_session_id == "child-123"
    assert req.origin_agent_name == "Search Agent"
    assert req.timeout_seconds == 3600


def test_hitl_request_timeout_defaults_to_one_day():
    """timeout_seconds must default to 86400 (1 day)."""
    req = HitlRequest(hitl_id="h1", type="provide_input", prompt="Q")
    assert req.timeout_seconds == 86400


def test_human_approval_required_holds_list():
    """HumanApprovalRequired must accept a list of HitlRequests."""
    r1 = HitlRequest(hitl_id="h1", type="approve_reject", prompt="Q1")
    r2 = HitlRequest(hitl_id="h2", type="choose", prompt="Q2")
    exc = HumanApprovalRequired([r1, r2])
    assert len(exc.requests) == 2
    assert exc.requests[0].hitl_id == "h1"
    assert exc.requests[1].hitl_id == "h2"


def test_human_approval_required_single_request():
    """Single-item list must work (normal hitl_tool path)."""
    r1 = HitlRequest(hitl_id="h1", type="provide_input", prompt="Q1")
    exc = HumanApprovalRequired([r1])
    assert len(exc.requests) == 1


def test_session_model_has_hitl_requests_field():
    """Session model must have hitl_requests field defaulting to empty list."""
    from everstaff.schema.memory import Session
    s = Session(session_id="s1", created_at="now", updated_at="now")
    assert s.hitl_requests == []


def test_session_model_hitl_requests_populated():
    """Session model must accept hitl_requests data."""
    from everstaff.schema.memory import Session
    s = Session(
        session_id="s1",
        created_at="now",
        updated_at="now",
        hitl_requests=[{"hitl_id": "h1", "status": "pending"}],
    )
    assert len(s.hitl_requests) == 1
    assert s.hitl_requests[0]["hitl_id"] == "h1"

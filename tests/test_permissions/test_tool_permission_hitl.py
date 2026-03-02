"""Test tool_permission HITL request type."""


def test_hitl_request_tool_permission_fields():
    from everstaff.protocols import HitlRequest
    req = HitlRequest(
        hitl_id="test-123",
        type="tool_permission",
        prompt="Agent wants to execute 'Bash'",
        tool_name="Bash",
        tool_args={"command": "git status"},
        options=["reject", "approve_once", "approve_session", "approve_permanent"],
    )
    assert req.type == "tool_permission"
    assert req.tool_name == "Bash"
    assert req.tool_args == {"command": "git status"}


def test_hitl_request_default_tool_fields():
    from everstaff.protocols import HitlRequest
    req = HitlRequest(hitl_id="test-456", type="approve_reject", prompt="test")
    assert req.tool_name == ""
    assert req.tool_args == {}


def test_hitl_resolution_grant_scope():
    from everstaff.schema.api_models import HitlResolution
    from datetime import datetime, timezone
    res = HitlResolution(
        decision="approved",
        grant_scope="session",
        resolved_at=datetime.now(timezone.utc),
    )
    assert res.grant_scope == "session"


def test_hitl_resolution_grant_scope_default_none():
    from everstaff.schema.api_models import HitlResolution
    from datetime import datetime, timezone
    res = HitlResolution(decision="approved", resolved_at=datetime.now(timezone.utc))
    assert res.grant_scope is None


def test_hitl_decision_grant_scope():
    from everstaff.api.hitl import HitlDecision
    d = HitlDecision(decision="approved", grant_scope="permanent")
    assert d.grant_scope == "permanent"


def test_hitl_request_payload_tool_fields():
    from everstaff.schema.hitl_models import HitlRequestPayload
    payload = HitlRequestPayload(
        type="tool_permission",
        prompt="test",
        tool_name="Bash",
        tool_args={"command": "ls"},
    )
    assert payload.tool_name == "Bash"
    assert payload.tool_args == {"command": "ls"}

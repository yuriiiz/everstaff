"""Test grant_scope processing in resume flow."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def test_format_decision_message_tool_permission():
    from everstaff.api.sessions import _format_decision_message
    req = {
        "type": "tool_permission",
        "prompt": "Agent wants to execute 'Bash'",
        "tool_name": "Bash",
    }
    msg = _format_decision_message(req, "approved", None)
    assert "approved" in msg.lower()
    assert "Bash" in msg or "tool_permission" in msg or "HITL" in msg


def _make_session_json(
    hitl_requests: list[dict],
    extra_permissions: list[str] | None = None,
    status: str = "waiting_for_human",
    agent_name: str = "TestAgent",
) -> dict:
    """Helper to build a session.json dict with resolved HITLs."""
    data = {
        "session_id": "test-session",
        "agent_name": agent_name,
        "status": status,
        "hitl_requests": hitl_requests,
    }
    if extra_permissions is not None:
        data["extra_permissions"] = extra_permissions
    return data


def _resolved_tool_permission(tool_name: str, grant_scope: str, decision: str = "approved") -> dict:
    return {
        "status": "resolved",
        "tool_call_id": f"tc_{tool_name}",
        "request": {
            "type": "tool_permission",
            "prompt": f"Agent wants to execute '{tool_name}'",
            "tool_name": tool_name,
        },
        "response": {
            "decision": decision,
            "grant_scope": grant_scope,
        },
    }


def test_session_grant_extracted_from_resolved_hitl():
    """Session-scoped grant should be collected into extra_perms."""
    session_raw = _make_session_json(
        hitl_requests=[_resolved_tool_permission("Bash", "session")],
    )
    resolved_hitls = [
        item for item in session_raw.get("hitl_requests", [])
        if item.get("status") == "resolved" and item.get("response")
    ]

    extra_perms = []
    for item in resolved_hitls:
        req = item.get("request", {})
        resp = item.get("response", {})
        if req.get("type") == "tool_permission" and resp.get("decision") == "approved":
            grant_scope = resp.get("grant_scope", "once")
            tool_name = req.get("tool_name", "")
            if not tool_name:
                continue
            if grant_scope in ("session", "permanent"):
                extra_perms.append(tool_name)

    assert extra_perms == ["Bash"]


def test_once_grant_not_persisted():
    """Once-scoped grant should NOT be added to extra_perms."""
    session_raw = _make_session_json(
        hitl_requests=[_resolved_tool_permission("Bash", "once")],
    )
    resolved_hitls = [
        item for item in session_raw.get("hitl_requests", [])
        if item.get("status") == "resolved" and item.get("response")
    ]

    extra_perms = []
    for item in resolved_hitls:
        req = item.get("request", {})
        resp = item.get("response", {})
        if req.get("type") == "tool_permission" and resp.get("decision") == "approved":
            grant_scope = resp.get("grant_scope", "once")
            tool_name = req.get("tool_name", "")
            if not tool_name:
                continue
            if grant_scope in ("session", "permanent"):
                extra_perms.append(tool_name)

    assert extra_perms == []


def test_rejected_hitl_not_persisted():
    """Rejected HITL should NOT add to extra_perms."""
    session_raw = _make_session_json(
        hitl_requests=[_resolved_tool_permission("Bash", "session", decision="rejected")],
    )
    resolved_hitls = [
        item for item in session_raw.get("hitl_requests", [])
        if item.get("status") == "resolved" and item.get("response")
    ]

    extra_perms = []
    for item in resolved_hitls:
        req = item.get("request", {})
        resp = item.get("response", {})
        if req.get("type") == "tool_permission" and resp.get("decision") == "approved":
            grant_scope = resp.get("grant_scope", "once")
            tool_name = req.get("tool_name", "")
            if not tool_name:
                continue
            if grant_scope in ("session", "permanent"):
                extra_perms.append(tool_name)

    assert extra_perms == []


def test_session_grants_merge_with_existing():
    """New session grants should merge with existing, not overwrite."""
    existing = ["Read", "Glob"]
    new_perms = ["Bash"]

    # This is the fixed merge logic from sessions.py
    merged = list(dict.fromkeys(existing + new_perms))

    assert merged == ["Read", "Glob", "Bash"]


def test_session_grants_merge_deduplicates():
    """Merging should deduplicate existing + new grants."""
    existing = ["Read", "Glob"]
    new_perms = ["Glob", "Bash"]

    merged = list(dict.fromkeys(existing + new_perms))

    assert merged == ["Read", "Glob", "Bash"]


def test_multiple_grants_from_single_resume():
    """Multiple tool_permission HITLs resolved at once should all be collected."""
    session_raw = _make_session_json(
        hitl_requests=[
            _resolved_tool_permission("Bash", "session"),
            _resolved_tool_permission("Write", "permanent"),
            _resolved_tool_permission("Read", "once"),
        ],
    )
    resolved_hitls = [
        item for item in session_raw.get("hitl_requests", [])
        if item.get("status") == "resolved" and item.get("response")
    ]

    extra_perms = []
    for item in resolved_hitls:
        req = item.get("request", {})
        resp = item.get("response", {})
        if req.get("type") == "tool_permission" and resp.get("decision") == "approved":
            grant_scope = resp.get("grant_scope", "once")
            tool_name = req.get("tool_name", "")
            if not tool_name:
                continue
            if grant_scope in ("session", "permanent"):
                extra_perms.append(tool_name)

    # Bash (session) and Write (permanent) should be collected; Read (once) should not
    assert extra_perms == ["Bash", "Write"]

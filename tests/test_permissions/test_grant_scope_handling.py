"""Test grant_scope processing in resume flow."""


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

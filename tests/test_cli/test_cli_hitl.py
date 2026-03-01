import json
import pytest
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch


def make_session_file(
    tmp_path: Path,
    session_id: str,
    hitl_type: str = "approve_reject",
    options: list | None = None,
    hitl_id: str = "test-hitl-1",
) -> Path:
    """Create a session.json with an embedded pending HITL request."""
    session_dir = tmp_path / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    default_options = ["yes", "no"] if hitl_type == "choose" else []
    data = {
        "session_id": session_id,
        "agent_name": "test-agent",
        "created_at": now,
        "updated_at": now,
        "status": "waiting_for_human",
        "metadata": {},
        "messages": [],
        "hitl_requests": [{
            "hitl_id": hitl_id,
            "tool_call_id": "call-test",
            "created_at": now,
            "timeout_seconds": 86400,
            "status": "pending",
            "origin_session_id": session_id,
            "origin_agent_name": "test-agent",
            "request": {
                "type": hitl_type,
                "prompt": "Should I proceed?",
                "options": options if options is not None else default_options,
                "context": "Some context here",
            },
            "response": None,
        }],
    }
    p = session_dir / "session.json"
    p.write_text(json.dumps(data))
    return p


def make_hitl_request(
    session_id: str,
    hitl_id: str = "test-hitl-1",
    hitl_type: str = "approve_reject",
    options: list | None = None,
):
    """Build a HitlRequest object matching what the runtime would raise."""
    from everstaff.protocols import HitlRequest
    default_options = ["yes", "no"] if hitl_type == "choose" else []
    return HitlRequest(
        hitl_id=hitl_id,
        type=hitl_type,
        prompt="Should I proceed?",
        options=options if options is not None else default_options,
        context="Some context here",
        tool_call_id="call-test",
        origin_session_id=session_id,
        origin_agent_name="test-agent",
        timeout_seconds=86400,
    )


@pytest.mark.asyncio
async def test_handle_cli_hitl_approve_reject(tmp_path):
    from everstaff.cli import _handle_cli_hitl

    hitl_id = "test-hitl-1"
    session_id = "sess-xyz"
    make_session_file(tmp_path, session_id, "approve_reject", hitl_id=hitl_id)
    hitl_req = make_hitl_request(session_id, hitl_id=hitl_id, hitl_type="approve_reject")

    resumed = []

    async def fake_resume(sid, agent_name, decision_text, config, tool_call_id="", **kwargs):
        resumed.append(sid)

    # Two inputs: decision, then empty comment
    with patch("builtins.input", side_effect=["approve", ""]), \
         patch("everstaff.api.sessions._resume_session_task", fake_resume):
        await _handle_cli_hitl(
            hitl_requests=[hitl_req],
            session_id=session_id,
            agent_name="test-agent",
            sessions_dir=tmp_path,
            config=None,
        )

    assert len(resumed) == 1
    # Decision must be written into session.json
    updated = json.loads((tmp_path / session_id / "session.json").read_text())
    hitl_item = updated["hitl_requests"][0]
    assert hitl_item["status"] == "resolved"
    assert hitl_item["response"]["decision"] == "approve"


@pytest.mark.asyncio
async def test_handle_cli_hitl_choose(tmp_path):
    from everstaff.cli import _handle_cli_hitl

    hitl_id = "test-hitl-2"
    session_id = "sess-abc"
    make_session_file(tmp_path, session_id, "choose", hitl_id=hitl_id)
    hitl_req = make_hitl_request(session_id, hitl_id=hitl_id, hitl_type="choose")

    resumed = []

    async def fake_resume(sid, agent_name, decision_text, config, tool_call_id="", **kwargs):
        resumed.append(sid)

    with patch("builtins.input", side_effect=["yes", ""]), \
         patch("everstaff.api.sessions._resume_session_task", fake_resume):
        await _handle_cli_hitl(
            hitl_requests=[hitl_req],
            session_id=session_id,
            agent_name="test-agent",
            sessions_dir=tmp_path,
            config=None,
        )

    assert len(resumed) == 1
    updated = json.loads((tmp_path / session_id / "session.json").read_text())
    decision = updated["hitl_requests"][0]["response"]["decision"]
    assert "yes" in decision.lower()


@pytest.mark.asyncio
async def test_handle_cli_hitl_choose_by_number(tmp_path):
    """choose type: user enters a number (1-based index) and decision contains the option text."""
    from everstaff.cli import _handle_cli_hitl

    hitl_id = "test-hitl-choose-num"
    session_id = "sess-choose-num"
    options = ["agent_1 (greeter)", "agent_2 (helper)", "agent_3 (analyst)"]
    make_session_file(tmp_path, session_id, "choose", options=options, hitl_id=hitl_id)
    hitl_req = make_hitl_request(session_id, hitl_id=hitl_id, hitl_type="choose", options=options)

    resumed = []

    async def fake_resume(sid, agent_name, decision_text, config, tool_call_id="", **kwargs):
        resumed.append(sid)

    # User picks option 2 by entering "2", then empty comment
    with patch("builtins.input", side_effect=["2", ""]), \
         patch("everstaff.api.sessions._resume_session_task", fake_resume):
        await _handle_cli_hitl(
            hitl_requests=[hitl_req],
            session_id=session_id,
            agent_name="test-agent",
            sessions_dir=tmp_path,
            config=None,
        )

    assert len(resumed) == 1
    updated = json.loads((tmp_path / session_id / "session.json").read_text())
    decision = updated["hitl_requests"][0]["response"]["decision"]
    # The decision must contain the option TEXT, not the number "2"
    assert "agent_2 (helper)" in decision, (
        f"Expected option text in decision, got: {decision!r}"
    )


@pytest.mark.asyncio
async def test_handle_cli_hitl_choose_multi_select(tmp_path):
    """choose type: user enters comma-separated numbers to select multiple options."""
    from everstaff.cli import _handle_cli_hitl

    hitl_id = "test-hitl-choose-multi"
    session_id = "sess-choose-multi"
    options = ["agent_1", "agent_2", "agent_3", "agent_4"]
    make_session_file(tmp_path, session_id, "choose", options=options, hitl_id=hitl_id)
    hitl_req = make_hitl_request(session_id, hitl_id=hitl_id, hitl_type="choose", options=options)

    resumed = []

    async def fake_resume(sid, agent_name, decision_text, config, tool_call_id="", **kwargs):
        resumed.append(sid)

    # User picks options 1 and 3 by entering "1,3", then empty comment
    with patch("builtins.input", side_effect=["1,3", ""]), \
         patch("everstaff.api.sessions._resume_session_task", fake_resume):
        await _handle_cli_hitl(
            hitl_requests=[hitl_req],
            session_id=session_id,
            agent_name="test-agent",
            sessions_dir=tmp_path,
            config=None,
        )

    assert len(resumed) == 1
    updated = json.loads((tmp_path / session_id / "session.json").read_text())
    decision = updated["hitl_requests"][0]["response"]["decision"]
    assert "agent_1" in decision, f"Expected agent_1 in decision, got: {decision!r}"
    assert "agent_3" in decision, f"Expected agent_3 in decision, got: {decision!r}"
    assert "agent_2" not in decision, f"agent_2 was not selected but appears in decision"


@pytest.mark.asyncio
async def test_handle_cli_hitl_choose_displays_numbered_list(tmp_path, capsys):
    """choose type: CLI prints a numbered list of options for the user to read."""
    from everstaff.cli import _handle_cli_hitl

    hitl_id = "test-hitl-choose-display"
    session_id = "sess-choose-display"
    options = ["alpha", "beta", "gamma"]
    make_session_file(tmp_path, session_id, "choose", options=options, hitl_id=hitl_id)
    hitl_req = make_hitl_request(session_id, hitl_id=hitl_id, hitl_type="choose", options=options)

    async def fake_resume(sid, agent_name, decision_text, config, tool_call_id="", **kwargs):
        pass

    with patch("builtins.input", side_effect=["1", ""]), \
         patch("everstaff.api.sessions._resume_session_task", fake_resume):
        await _handle_cli_hitl(
            hitl_requests=[hitl_req],
            session_id=session_id,
            agent_name="test-agent",
            sessions_dir=tmp_path,
            config=None,
        )

    captured = capsys.readouterr()
    # Numbered entries must be printed
    assert "1." in captured.out and "alpha" in captured.out, "Option 1 not shown as numbered"
    assert "2." in captured.out and "beta" in captured.out, "Option 2 not shown as numbered"
    assert "3." in captured.out and "gamma" in captured.out, "Option 3 not shown as numbered"


@pytest.mark.asyncio
async def test_handle_cli_hitl_missing_session(tmp_path, capsys):
    """If session.json is missing, print an error and return without crashing."""
    from everstaff.cli import _handle_cli_hitl
    from everstaff.protocols import HitlRequest

    hitl_req = HitlRequest(
        hitl_id="no-such-id",
        type="approve_reject",
        prompt="Test",
        origin_session_id="no-such-session",
        origin_agent_name="test-agent",
    )

    # No session directory created at all
    await _handle_cli_hitl(
        hitl_requests=[hitl_req],
        session_id="no-such-session",
        agent_name="test-agent",
        sessions_dir=tmp_path,
        config=None,
    )
    captured = capsys.readouterr()
    assert "[HITL]" in captured.out

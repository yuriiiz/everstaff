# tests/channels/test_lark_ws_channel.py
"""Tests for LarkWsChannel — the long-connection (WebSocket) Lark HITL channel."""
import json as _json
import asyncio
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch, call

from everstaff.protocols import HitlRequest, HitlResolution


@pytest.fixture
def channel_manager_mock():
    """A minimal ChannelManager-like mock with a resolve() coroutine."""
    mgr = MagicMock()
    mgr.resolve = AsyncMock(return_value=True)
    return mgr


@pytest.fixture
def lark_ws_channel(channel_manager_mock):
    from everstaff.channels.lark_ws import LarkWsChannel
    ch = LarkWsChannel(
        app_id="app_123",
        app_secret="secret_456",
        chat_id="chat_001",
        channel_manager=channel_manager_mock,
    )
    # Mock HTTP helpers (same pattern as LarkChannel tests)
    ch._get_access_token = AsyncMock(return_value="token_xyz")
    ch._send_card = AsyncMock(return_value="msg_abc")
    ch._update_card = AsyncMock()
    return ch


# --- HitlRequest created_at ---

def test_hitl_request_has_created_at():
    """HitlRequest should auto-populate created_at."""
    req = HitlRequest(hitl_id="h1", type="approve_reject", prompt="test")
    assert req.created_at is not None
    assert isinstance(req.created_at, datetime)


# --- send_request tests ---

@pytest.mark.asyncio
async def test_send_request_calls_send_card(lark_ws_channel):
    """send_request must call _send_card with a payload containing the hitl_id."""
    req = HitlRequest(hitl_id="h1", type="approve_reject", prompt="Deploy to prod?")
    await lark_ws_channel.send_request("session-1", req)

    lark_ws_channel._send_card.assert_called_once()
    assert "h1" in str(lark_ws_channel._send_card.call_args)


@pytest.mark.asyncio
async def test_send_request_stores_message_id(lark_ws_channel):
    """send_request must store the returned message_id in memory."""
    req = HitlRequest(hitl_id="h1", type="approve_reject", prompt="Allow?")
    await lark_ws_channel.send_request("session-1", req)

    assert lark_ws_channel._hitl_message_ids.get("h1") == "msg_abc"


@pytest.mark.asyncio
async def test_send_request_stores_session_id(lark_ws_channel):
    """send_request must store session_id mapping."""
    req = HitlRequest(hitl_id="h1", type="approve_reject", prompt="Allow?")
    await lark_ws_channel.send_request("session-42", req)
    assert lark_ws_channel._hitl_session_ids.get("h1") == "session-42"


# --- on_resolved tests ---

@pytest.mark.asyncio
async def test_on_resolved_updates_card(lark_ws_channel):
    """on_resolved must call _update_card when message_id is known."""
    lark_ws_channel._hitl_message_ids["h1"] = "msg_abc"
    lark_ws_channel._username_cache["lark_user"] = "Zhang San"
    resolution = HitlResolution(
        decision="approved",
        resolved_at=datetime.now(timezone.utc),
        resolved_by="lark_user",
    )
    await lark_ws_channel.on_resolved("h1", resolution)

    lark_ws_channel._update_card.assert_called_once()


@pytest.mark.asyncio
async def test_on_resolved_cleans_up(lark_ws_channel):
    """on_resolved must remove hitl_id from all tracking dicts."""
    lark_ws_channel._hitl_message_ids["h1"] = "msg_abc"
    lark_ws_channel._hitl_requests["h1"] = HitlRequest(hitl_id="h1", type="approve_reject", prompt="test")
    lark_ws_channel._hitl_session_ids["h1"] = "sess-1"
    lark_ws_channel._username_cache["lark_user"] = "User"
    resolution = HitlResolution(
        decision="rejected",
        resolved_at=datetime.now(timezone.utc),
        resolved_by="lark_user",
    )
    await lark_ws_channel.on_resolved("h1", resolution)

    assert "h1" not in lark_ws_channel._hitl_message_ids
    assert "h1" not in lark_ws_channel._hitl_requests
    assert "h1" not in lark_ws_channel._hitl_session_ids


@pytest.mark.asyncio
async def test_on_resolved_no_message_id_is_noop(lark_ws_channel):
    """on_resolved with unknown hitl_id must not call _update_card."""
    resolution = HitlResolution(
        decision="approved",
        resolved_at=datetime.now(timezone.utc),
        resolved_by="human",
    )
    await lark_ws_channel.on_resolved("unknown-h", resolution)
    lark_ws_channel._update_card.assert_not_called()


# --- card builders ---

def test_build_card_uses_markdown(lark_ws_channel):
    """_build_card should use lark_md for prompt."""
    req = HitlRequest(hitl_id="h1", type="approve_reject", prompt="Deploy?")
    card = lark_ws_channel._build_card(req, "h1", "sess-1")
    elements = card["elements"]
    assert elements[0]["text"]["tag"] == "lark_md"
    assert "**Deploy?**" in elements[0]["text"]["content"]


def test_build_card_has_session_link(lark_ws_channel):
    """_build_card should include session link in note when web_url is set."""
    lark_ws_channel._web_url = "http://localhost:3000"
    req = HitlRequest(hitl_id="h1", type="approve_reject", prompt="Deploy?")
    card = lark_ws_channel._build_card(req, "h1", "session-abc-123")
    card_json = _json.dumps(card)
    assert "http://localhost:3000/sessions/session-abc-123" in card_json


def test_build_card_tool_args_collapsed(lark_ws_channel):
    """_build_card should use collapsible_panel for tool arguments."""
    req = HitlRequest(
        hitl_id="h1", type="tool_permission", prompt="Allow Bash?",
        tool_name="Bash", tool_args={"command": "ls -la"},
    )
    card = lark_ws_channel._build_card(req, "h1", "sess-1")
    card_json = _json.dumps(card)
    assert "collapsible_panel" in card_json
    assert '"expanded": false' in card_json


def test_build_card_header_orange(lark_ws_channel):
    """Pending card must have orange header."""
    req = HitlRequest(hitl_id="h1", type="approve_reject", prompt="Deploy?")
    card = lark_ws_channel._build_card(req, "h1")
    assert card["header"]["template"] == "orange"
    assert "Needs Approval" in card["header"]["title"]["content"]


def test_resolved_card_preserves_prompt(lark_ws_channel):
    """Resolved card must keep the original prompt."""
    req = HitlRequest(hitl_id="h1", type="approve_reject", prompt="Deploy to prod?")
    card = lark_ws_channel._build_resolved_card("approved", "Zhang San", req, "sess-1")
    card_json = _json.dumps(card)
    assert "Deploy to prod?" in card_json
    assert "Zhang San" in card_json
    assert "Approved" in card_json


def test_resolved_card_has_green_header(lark_ws_channel):
    """Resolved card must have green header."""
    card = lark_ws_channel._build_resolved_card("approved", "user", None, "")
    assert card["header"]["template"] == "green"


def test_resolved_card_shows_decision_label(lark_ws_channel):
    """Resolved card should show human-readable decision label."""
    req = HitlRequest(hitl_id="h1", type="tool_permission", prompt="Allow?")
    card = lark_ws_channel._build_resolved_card("approve_permanent", "User", req)
    card_json = _json.dumps(card)
    assert "Approved (always)" in card_json


def test_build_expired_card_structure(lark_ws_channel):
    """Expired card should have grey header and expiration warning."""
    req = HitlRequest(hitl_id="h1", type="tool_permission", prompt="Allow Bash?",
                      tool_name="Bash", tool_args={"command": "ls"})
    card = lark_ws_channel._build_expired_card(req, "sess-1")
    assert card["header"]["template"] == "grey"
    card_json = _json.dumps(card)
    assert "expired" in card_json.lower()
    assert "Allow Bash?" in card_json
    assert "collapsible_panel" in card_json


def test_build_notify_card_uses_markdown(lark_ws_channel):
    """Notify card should use lark_md for prompt."""
    req = HitlRequest(hitl_id="h1", type="notify", prompt="Task completed")
    card = lark_ws_channel._build_notify_card(req)
    assert card["header"]["template"] == "blue"
    assert card["elements"][0]["text"]["tag"] == "lark_md"


# --- username resolution ---

@pytest.mark.asyncio
async def test_resolve_username_caches(lark_ws_channel):
    """_resolve_username caches results."""
    lark_ws_channel._username_cache["ou_123"] = "Zhang San"
    name = await lark_ws_channel._resolve_username("ou_123")
    assert name == "Zhang San"
    lark_ws_channel._get_access_token.assert_not_called()


# --- expiration detection ---

def test_expiration_detection(lark_ws_channel):
    """Expired requests should be detectable by age > timeout_seconds."""
    req = HitlRequest(
        hitl_id="h-exp", type="approve_reject", prompt="Expired?",
        timeout_seconds=1,
        created_at=datetime.now(timezone.utc) - timedelta(seconds=120),
    )
    lark_ws_channel._hitl_requests["h-exp"] = req

    now = datetime.now(timezone.utc)
    expired_ids = []
    for hid, r in list(lark_ws_channel._hitl_requests.items()):
        if r.timeout_seconds > 0 and (now - r.created_at).total_seconds() > r.timeout_seconds:
            expired_ids.append(hid)
    assert "h-exp" in expired_ids


# --- card action handler ---

def _make_card_action_data(value: dict, form_value=None, open_id="user_001"):
    """Build a mock P2CardActionTrigger with data nested under .event."""
    data = MagicMock()
    data.event.action.value = value
    data.event.action.form_value = form_value or {}
    data.event.operator.open_id = open_id
    return data


@pytest.mark.asyncio
async def test_handle_card_action_calls_resolve(lark_ws_channel, channel_manager_mock):
    """_handle_card_action must call channel_manager.resolve() with correct hitl_id."""
    await lark_ws_channel._handle_card_action("h1", "approved", "user_001")

    channel_manager_mock.resolve.assert_called_once()
    call_args = channel_manager_mock.resolve.call_args
    assert call_args[0][0] == "h1"


@pytest.mark.asyncio
async def test_handle_card_action_with_grant_scope(lark_ws_channel, channel_manager_mock):
    """_handle_card_action must pass grant_scope to resolution."""
    await lark_ws_channel._handle_card_action("h1", "approved", "user_001", grant_scope="session")

    channel_manager_mock.resolve.assert_called_once()
    resolution = channel_manager_mock.resolve.call_args[0][1]
    assert resolution.grant_scope == "session"


@pytest.mark.asyncio
async def test_handle_card_action_input_type(lark_ws_channel, channel_manager_mock):
    """_handle_card_action passes decision directly (parsing done upstream)."""
    await lark_ws_channel._handle_card_action("h2", "my free text", "user_002")

    channel_manager_mock.resolve.assert_called_once()
    resolution = channel_manager_mock.resolve.call_args[0][1]
    assert resolution.decision == "my free text"


@pytest.mark.asyncio
async def test_parse_card_action_extracts_grant_scope(lark_ws_channel):
    """_parse_card_action must extract grant_scope from button value."""
    from everstaff.channels.lark_ws import LarkWsChannel
    data = _make_card_action_data({"hitl_id": "h1", "decision": "approved", "grant_scope": "permanent"})
    hitl_id, decision, resolved_by, grant_scope, permission_pattern = LarkWsChannel._parse_card_action(data)
    assert hitl_id == "h1"
    assert decision == "approved"
    assert grant_scope == "permanent"
    assert permission_pattern is None


@pytest.mark.asyncio
async def test_parse_card_action_missing_hitl_id(lark_ws_channel):
    """_parse_card_action with no hitl_id returns empty tuple."""
    from everstaff.channels.lark_ws import LarkWsChannel
    data = _make_card_action_data({"decision": "approved"}, open_id="user_003")
    hitl_id, decision, resolved_by, grant_scope, permission_pattern = LarkWsChannel._parse_card_action(data)
    assert hitl_id == ""


# --- start / stop lifecycle ---

@pytest.mark.asyncio
async def test_start_launches_daemon_thread(lark_ws_channel):
    """start() must set _started = True and launch a daemon thread."""
    with patch("threading.Thread") as mock_thread_cls:
        mock_thread = MagicMock()
        mock_thread_cls.return_value = mock_thread
        await lark_ws_channel.start()
    assert lark_ws_channel._started is True
    mock_thread_cls.assert_called_once()
    assert mock_thread_cls.call_args[1]["daemon"] is True
    mock_thread.start.assert_called_once()
    # Clean up expiration task
    if lark_ws_channel._expiration_task:
        lark_ws_channel._expiration_task.cancel()


@pytest.mark.asyncio
async def test_start_is_idempotent(lark_ws_channel):
    """Calling start() twice must not create a second thread."""
    with patch("threading.Thread") as mock_thread_cls:
        mock_thread = MagicMock()
        mock_thread_cls.return_value = mock_thread
        await lark_ws_channel.start()
        await lark_ws_channel.start()
    mock_thread_cls.assert_called_once()
    # Clean up expiration task
    if lark_ws_channel._expiration_task:
        lark_ws_channel._expiration_task.cancel()


@pytest.mark.asyncio
async def test_stop_cancels_expiration_task(lark_ws_channel):
    """stop() must cancel the expiration polling task."""
    mock_task = MagicMock()
    lark_ws_channel._expiration_task = mock_task
    lark_ws_channel._started = True
    await lark_ws_channel.stop()
    mock_task.cancel.assert_called_once()
    assert lark_ws_channel._expiration_task is None
    assert lark_ws_channel._started is False


@pytest.mark.asyncio
async def test_stop_sets_stopped(lark_ws_channel):
    """stop() must set _started = False."""
    lark_ws_channel._started = True
    await lark_ws_channel.stop()
    assert lark_ws_channel._started is False

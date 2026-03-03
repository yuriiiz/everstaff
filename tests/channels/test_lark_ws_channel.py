# tests/channels/test_lark_ws_channel.py
"""Tests for LarkWsChannel — the long-connection (WebSocket) Lark HITL channel."""
import json as _json
import asyncio
import pytest
from datetime import datetime, timezone
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


# --- send_request tests (same behaviour as LarkChannel) ---

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
async def test_on_resolved_updates_card(lark_ws_channel):
    """on_resolved must call _update_card when message_id is known."""
    lark_ws_channel._hitl_message_ids["h1"] = "msg_abc"
    resolution = HitlResolution(
        decision="approved",
        resolved_at=datetime.now(timezone.utc),
        resolved_by="lark_user",
    )
    await lark_ws_channel.on_resolved("h1", resolution)

    lark_ws_channel._update_card.assert_called_once()


@pytest.mark.asyncio
async def test_on_resolved_cleans_up(lark_ws_channel):
    """on_resolved must remove hitl_id from _hitl_message_ids after update."""
    lark_ws_channel._hitl_message_ids["h1"] = "msg_abc"
    resolution = HitlResolution(
        decision="rejected",
        resolved_at=datetime.now(timezone.utc),
        resolved_by="lark_user",
    )
    await lark_ws_channel.on_resolved("h1", resolution)

    assert "h1" not in lark_ws_channel._hitl_message_ids


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


# --- card action handler (the core WS-mode behaviour) ---

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


@pytest.mark.asyncio
async def test_start_is_idempotent(lark_ws_channel):
    """Calling start() twice must not create a second thread."""
    with patch("threading.Thread") as mock_thread_cls:
        mock_thread = MagicMock()
        mock_thread_cls.return_value = mock_thread
        await lark_ws_channel.start()
        await lark_ws_channel.start()
    mock_thread_cls.assert_called_once()


@pytest.mark.asyncio
async def test_stop_sets_stopped(lark_ws_channel):
    """stop() must set _started = False."""
    lark_ws_channel._started = True
    await lark_ws_channel.stop()
    assert lark_ws_channel._started is False

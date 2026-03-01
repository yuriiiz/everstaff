"""Tests for HITL notify type — non-blocking user notification."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from everstaff.protocols import HitlRequest, HitlResolution


def test_hitl_request_notify_type():
    """HitlRequest with type='notify' must be constructable."""
    req = HitlRequest(hitl_id="n1", type="notify", prompt="Hello")
    assert req.type == "notify"


def test_lark_channel_builds_notify_card():
    """LarkChannel must build a display-only card for notify type."""
    from everstaff.channels.lark import LarkChannel
    ch = LarkChannel(
        app_id="a", app_secret="s", verification_token="t", chat_id="c"
    )
    req = HitlRequest(hitl_id="n1", type="notify", prompt="FYI: task started")
    card = ch._build_notify_card(req)
    # Must be blue (informational) and have no action buttons
    assert card["header"]["template"] == "blue"
    card_str = str(card)
    assert "FYI: task started" in card_str
    # No action buttons
    for elem in card.get("elements", []):
        assert elem.get("tag") != "action" or not elem.get("actions"), \
            "notify card must not contain action elements with buttons"


@pytest.mark.asyncio
async def test_lark_send_request_notify_does_not_store_mapping():
    """send_request with notify type must NOT store message_id mapping."""
    from everstaff.channels.lark import LarkChannel
    ch = LarkChannel(
        app_id="a", app_secret="s", verification_token="t", chat_id="c"
    )
    ch._get_access_token = AsyncMock(return_value="tok")
    ch._send_card = AsyncMock(return_value="msg_123")

    req = HitlRequest(hitl_id="n1", type="notify", prompt="Notice!")
    await ch.send_request("session-1", req)

    # Must NOT store in _hitl_message_ids (notify is fire-and-forget)
    assert "n1" not in ch._hitl_message_ids
    # Must have called _send_card
    ch._send_card.assert_called_once()

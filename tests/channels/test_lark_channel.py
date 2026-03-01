# tests/channels/test_lark_channel.py
import json as _json
import pytest
from unittest.mock import AsyncMock, patch
from datetime import datetime, timezone
from everstaff.protocols import HitlRequest, HitlResolution
from everstaff.channels.lark import LarkChannel
from everstaff.storage.local import LocalFileStore


@pytest.fixture
def lark_channel():
    ch = LarkChannel(
        app_id="app_123",
        app_secret="secret_456",
        verification_token="token_789",
        chat_id="chat_001",
    )
    ch._get_access_token = AsyncMock(return_value="token_xyz")
    ch._send_card = AsyncMock(return_value="msg_abc")
    ch._update_card = AsyncMock()
    return ch


@pytest.mark.asyncio
async def test_send_request_calls_lark_api(lark_channel):
    """send_request must call _send_card with a payload containing the hitl_id."""
    req = HitlRequest(hitl_id="h1", type="approve_reject", prompt="Deploy to prod?")
    await lark_channel.send_request("session-1", req)

    lark_channel._send_card.assert_called_once()
    # Verify hitl_id is embedded in the card payload
    call_args = str(lark_channel._send_card.call_args)
    assert "h1" in call_args


@pytest.mark.asyncio
async def test_send_request_stores_message_id(lark_channel):
    """send_request must store the message_id returned by _send_card."""
    req = HitlRequest(hitl_id="h1", type="approve_reject", prompt="Allow?")
    await lark_channel.send_request("session-1", req)

    assert lark_channel._hitl_message_ids.get("h1") == "msg_abc"


@pytest.mark.asyncio
async def test_on_resolved_updates_card(lark_channel):
    """on_resolved must call _update_card when message_id is known."""
    lark_channel._hitl_message_ids["h1"] = "msg_abc"

    resolution = HitlResolution(
        decision="approved",
        resolved_at=datetime.now(timezone.utc),
        resolved_by="lark_user",
    )
    await lark_channel.on_resolved("h1", resolution)

    lark_channel._update_card.assert_called_once()


@pytest.mark.asyncio
async def test_on_resolved_cleans_up(lark_channel):
    """on_resolved must remove hitl_id from _hitl_message_ids after update."""
    lark_channel._hitl_message_ids["h1"] = "msg_abc"
    resolution = HitlResolution(
        decision="rejected",
        resolved_at=datetime.now(timezone.utc),
        resolved_by="lark_user",
    )
    await lark_channel.on_resolved("h1", resolution)

    assert "h1" not in lark_channel._hitl_message_ids


@pytest.mark.asyncio
async def test_on_resolved_no_message_id_is_noop(lark_channel):
    """on_resolved with unknown hitl_id must not call _update_card."""
    resolution = HitlResolution(
        decision="approved",
        resolved_at=datetime.now(timezone.utc),
        resolved_by="human",
    )
    await lark_channel.on_resolved("unknown-h", resolution)
    lark_channel._update_card.assert_not_called()


@pytest.mark.asyncio
async def test_verify_webhook_correct_token(lark_channel):
    """verify_webhook must return True for matching token."""
    assert lark_channel.verify_webhook("token_789") is True


@pytest.mark.asyncio
async def test_verify_webhook_wrong_token(lark_channel):
    """verify_webhook must return False for wrong token."""
    assert lark_channel.verify_webhook("wrong_token") is False


def test_build_card_approve_reject(lark_channel):
    """_build_card for approve_reject must include Approve and Reject buttons."""
    req = HitlRequest(hitl_id="h1", type="approve_reject", prompt="Deploy?")
    card = lark_channel._build_card(req, "h1")
    card_str = str(card)
    assert "Approve" in card_str
    assert "Reject" in card_str
    assert "h1" in card_str


def test_build_card_choose(lark_channel):
    """_build_card for choose must include all options as buttons."""
    req = HitlRequest(hitl_id="h2", type="choose", prompt="Pick one?", options=["A", "B", "C"])
    card = lark_channel._build_card(req, "h2")
    card_str = str(card)
    assert "A" in card_str and "B" in card_str and "C" in card_str


@pytest.fixture
def store(tmp_path):
    return LocalFileStore(str(tmp_path))


@pytest.fixture
def lark_channel_with_store(tmp_path, store):
    ch = LarkChannel(
        app_id="app_123",
        app_secret="secret_456",
        verification_token="token_789",
        chat_id="chat_001",
        file_store=store,
    )
    ch._get_access_token = AsyncMock(return_value="token_xyz")
    ch._send_card = AsyncMock(return_value="msg_abc")
    ch._update_card = AsyncMock()
    return ch


@pytest.mark.asyncio
async def test_send_request_persists_mapping(lark_channel_with_store, store):
    """send_request must write hitl-lark/{hitl_id}.json with message_id."""
    req = HitlRequest(hitl_id="h1", type="approve_reject", prompt="Deploy?")
    await lark_channel_with_store.send_request("session-1", req)

    data = _json.loads((await store.read("hitl-lark/h1.json")).decode())
    assert data["message_id"] == "msg_abc"
    assert data["hitl_id"] == "h1"


@pytest.mark.asyncio
async def test_on_resolved_reads_from_store(lark_channel_with_store, store):
    """on_resolved must read message_id from FileStore, not memory."""
    mapping = {"hitl_id": "h1", "message_id": "msg_xyz"}
    await store.write("hitl-lark/h1.json", _json.dumps(mapping).encode())

    resolution = HitlResolution(
        decision="approved",
        resolved_at=datetime.now(timezone.utc),
        resolved_by="lark_user",
    )
    await lark_channel_with_store.on_resolved("h1", resolution)

    lark_channel_with_store._update_card.assert_called_once()


@pytest.mark.asyncio
async def test_on_resolved_deletes_mapping(lark_channel_with_store, store):
    """on_resolved must delete hitl-lark/{hitl_id}.json after resolving."""
    mapping = {"hitl_id": "h1", "message_id": "msg_xyz"}
    await store.write("hitl-lark/h1.json", _json.dumps(mapping).encode())

    resolution = HitlResolution(
        decision="approved",
        resolved_at=datetime.now(timezone.utc),
        resolved_by="lark_user",
    )
    await lark_channel_with_store.on_resolved("h1", resolution)

    assert not await store.exists("hitl-lark/h1.json")

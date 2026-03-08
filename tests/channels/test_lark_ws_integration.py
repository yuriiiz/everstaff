"""Integration test: multiple channels sharing one connection."""
import pytest
from unittest.mock import MagicMock, AsyncMock

from everstaff.channels.lark_ws_connection import LarkWsConnection
from everstaff.channels.lark_ws import LarkWsChannel
from everstaff.core.config import LarkWsChannelConfig
from everstaff.core.factories import build_lark_connections
from everstaff.protocols import HitlRequest, HitlResolution


def test_two_channels_share_connection():
    """Two LarkWsChannelConfigs with the same app_id share one connection."""
    configs = {
        "ch_a": LarkWsChannelConfig(type="lark_ws", app_id="app1", app_secret="s", chat_id="oc_a"),
        "ch_b": LarkWsChannelConfig(type="lark_ws", app_id="app1", app_secret="s", chat_id="oc_b"),
    }
    connections = build_lark_connections(configs)
    assert len(connections) == 1

    conn = connections["app1"]
    ch_a = LarkWsChannel(connection=conn, chat_id="oc_a")
    ch_b = LarkWsChannel(connection=conn, chat_id="oc_b")
    assert ch_a._connection is ch_b._connection
    assert ch_a._chat_id == "oc_a"
    assert ch_b._chat_id == "oc_b"


def test_chat_routing():
    """Chat routes correctly resolve to agent names."""
    conn = LarkWsConnection(app_id="app1", app_secret="s")
    conn.register_chat_route("oc_a", "agent_a")
    conn.register_chat_route("oc_b", "agent_b")
    assert conn._resolve_agent("oc_a") == "agent_a"
    assert conn._resolve_agent("oc_b") == "agent_b"
    assert conn._resolve_agent("oc_unknown") is None


def test_card_action_type_routing():
    """parse_card_value correctly identifies hitl vs other types."""
    hitl_value = {"type": "hitl", "hitl_id": "h1", "decision": "approved"}
    action_type, parsed = LarkWsConnection._parse_card_value(hitl_value)
    assert action_type == "hitl"

    feedback_value = {"type": "feedback", "rating": 5}
    action_type, parsed = LarkWsConnection._parse_card_value(feedback_value)
    assert action_type == "feedback"

    # Default to hitl when type missing
    no_type_value = {"hitl_id": "h1", "decision": "approved"}
    action_type, parsed = LarkWsConnection._parse_card_value(no_type_value)
    assert action_type == "hitl"


@pytest.mark.asyncio
async def test_channel_send_and_resolve_flow():
    """Full send_request + on_resolved flow through connection delegation."""
    conn = MagicMock(spec=LarkWsConnection)
    conn._app_id = "app1"
    conn.send_card = AsyncMock(return_value="msg_001")
    conn.update_card = AsyncMock()

    ch = LarkWsChannel(connection=conn, chat_id="oc_chatA", bot_name="TestBot")

    # Send a request
    request = HitlRequest(hitl_id="h1", type="approve_reject", prompt="Deploy?")
    await ch.send_request("session1", request)

    conn.send_card.assert_called_once()
    assert conn.send_card.call_args[0][0] == "oc_chatA"
    assert ch._hitl_message_ids["h1"] == "msg_001"

    # Resolve
    from datetime import datetime, timezone
    resolution = HitlResolution(
        decision="approved",
        resolved_at=datetime.now(timezone.utc),
        resolved_by="user_001",
    )
    await ch.on_resolved("h1", resolution)

    conn.update_card.assert_called_once()
    assert conn.update_card.call_args[0][0] == "msg_001"
    assert "h1" not in ch._hitl_message_ids


def test_all_button_types_have_hitl_type():
    """Verify type=hitl on all card button types."""
    conn = MagicMock(spec=LarkWsConnection)
    conn._app_id = "app1"
    ch = LarkWsChannel(connection=conn, chat_id="oc_a")

    # approve_reject
    request = HitlRequest(hitl_id="h1", type="approve_reject", prompt="OK?")
    card = ch._build_card(request, "h1")
    for elem in card["elements"]:
        if elem.get("tag") == "action":
            for btn in elem["actions"]:
                assert btn["value"]["type"] == "hitl"

    # choose
    request = HitlRequest(hitl_id="h2", type="choose", prompt="Pick", options=["A", "B"])
    card = ch._build_card(request, "h2")
    for elem in card["elements"]:
        if elem.get("tag") == "action":
            for btn in elem["actions"]:
                assert btn["value"]["type"] == "hitl"

    # provide_input
    request = HitlRequest(hitl_id="h3", type="provide_input", prompt="Enter")
    card = ch._build_card(request, "h3")
    for elem in card["elements"]:
        if elem.get("tag") == "form":
            for sub in elem["elements"]:
                if sub.get("tag") == "button":
                    assert sub["value"]["type"] == "hitl"

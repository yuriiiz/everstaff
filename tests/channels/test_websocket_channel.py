# tests/channels/test_websocket_channel.py
import pytest
from unittest.mock import AsyncMock
from datetime import datetime, timezone
from everstaff.protocols import HitlRequest, HitlResolution
from everstaff.channels.websocket import WebSocketChannel


@pytest.mark.asyncio
async def test_send_request_pushes_hitl_event():
    """send_request should call broadcast_fn with a hitl_request event dict."""
    broadcast_fn = AsyncMock()
    channel = WebSocketChannel(broadcast_fn=broadcast_fn)

    req = HitlRequest(hitl_id="h1", type="approve_reject", prompt="Allow?")
    await channel.send_request("session-1", req)

    broadcast_fn.assert_called_once()
    event = broadcast_fn.call_args[0][0]
    assert event["type"] == "hitl_request"
    assert event["hitl_id"] == "h1"
    assert event["session_id"] == "session-1"
    assert event["prompt"] == "Allow?"


@pytest.mark.asyncio
async def test_on_resolved_broadcasts_resolved_event():
    """on_resolved should broadcast a hitl_resolved event."""
    broadcast_fn = AsyncMock()
    channel = WebSocketChannel(broadcast_fn=broadcast_fn)

    resolution = HitlResolution(
        decision="approved",
        resolved_at=datetime.now(timezone.utc),
        resolved_by="human",
    )
    await channel.on_resolved("h1", resolution)

    broadcast_fn.assert_called_once()
    event = broadcast_fn.call_args[0][0]
    assert event["type"] == "hitl_resolved"
    assert event["hitl_id"] == "h1"
    assert event["decision"] == "approved"
    assert event["resolved_by"] == "human"


@pytest.mark.asyncio
async def test_start_and_stop_are_noops():
    """start() and stop() must not raise."""
    channel = WebSocketChannel(broadcast_fn=AsyncMock())
    await channel.start()
    await channel.stop()


@pytest.mark.asyncio
async def test_broadcast_fn_receives_dict():
    """broadcast_fn must receive a plain dict (JSON-serializable)."""
    import json
    received = []
    async def capture(event):
        received.append(event)

    channel = WebSocketChannel(broadcast_fn=capture)
    req = HitlRequest(hitl_id="h2", type="choose", prompt="Pick?", options=["A", "B"])
    await channel.send_request("session-2", req)

    assert len(received) == 1
    # Must be JSON-serializable
    json.dumps(received[0])
    assert received[0]["options"] == ["A", "B"]

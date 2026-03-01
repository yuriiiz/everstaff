# tests/channels/test_channel_manager.py
import asyncio
import pytest
from datetime import datetime, timezone
from everstaff.protocols import HitlRequest, HitlResolution
from everstaff.channels.manager import ChannelManager


class MockChannel:
    def __init__(self):
        self.sent_requests = []
        self.resolved_ids = []
        self.started = False
        self.stopped = False

    async def send_request(self, session_id: str, request: HitlRequest) -> None:
        self.sent_requests.append((session_id, request))

    async def on_resolved(self, hitl_id: str, resolution: HitlResolution) -> None:
        self.resolved_ids.append(hitl_id)

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True


def make_request(hitl_id="h1"):
    return HitlRequest(hitl_id=hitl_id, type="approve_reject", prompt="Allow?")


def make_resolution():
    return HitlResolution(
        decision="approved",
        resolved_at=datetime.now(timezone.utc),
        resolved_by="human",
    )


@pytest.mark.asyncio
async def test_broadcast_sends_to_all_channels():
    manager = ChannelManager()
    ch1, ch2 = MockChannel(), MockChannel()
    manager.register(ch1)
    manager.register(ch2)

    req = make_request()
    await manager.broadcast("session-1", req)

    assert len(ch1.sent_requests) == 1
    assert len(ch2.sent_requests) == 1
    assert ch1.sent_requests[0][0] == "session-1"


@pytest.mark.asyncio
async def test_resolve_notifies_all_channels():
    manager = ChannelManager()
    ch1, ch2, ch3 = MockChannel(), MockChannel(), MockChannel()
    manager.register(ch1)
    manager.register(ch2)
    manager.register(ch3)

    resolution = make_resolution()
    result = await manager.resolve("h1", resolution)

    assert result is True
    assert "h1" in ch1.resolved_ids
    assert "h1" in ch2.resolved_ids
    assert "h1" in ch3.resolved_ids


@pytest.mark.asyncio
async def test_resolve_is_idempotent():
    manager = ChannelManager()
    ch = MockChannel()
    manager.register(ch)

    resolution = make_resolution()
    first = await manager.resolve("h1", resolution)
    second = await manager.resolve("h1", resolution)

    assert first is True
    assert second is False
    assert ch.resolved_ids.count("h1") == 1  # notified only once


@pytest.mark.asyncio
async def test_start_all_and_stop_all():
    manager = ChannelManager()
    ch1, ch2 = MockChannel(), MockChannel()
    manager.register(ch1)
    manager.register(ch2)

    await manager.start_all()
    assert ch1.started and ch2.started

    await manager.stop_all()
    assert ch1.stopped and ch2.stopped

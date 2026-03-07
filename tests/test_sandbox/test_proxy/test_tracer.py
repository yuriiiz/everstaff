"""Tests for ProxyTracer."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from everstaff.protocols import TraceEvent
from everstaff.sandbox.proxy.tracer import ProxyTracer


@pytest.mark.asyncio
class TestProxyTracer:
    async def test_on_event_sends_notification(self):
        channel = MagicMock()
        channel.send_notification = AsyncMock()
        tracer = ProxyTracer(channel)

        event = TraceEvent(kind="session_start", session_id="s1", data={"agent_name": "test"})
        tracer.on_event(event)

        # Give the background task time to execute
        await asyncio.sleep(0.05)

        channel.send_notification.assert_called_once()
        call_args = channel.send_notification.call_args
        assert call_args[0][0] == "tracer.event"
        params = call_args[0][1]
        assert params["kind"] == "session_start"
        assert params["session_id"] == "s1"

    async def test_aflush_is_noop(self):
        channel = MagicMock()
        channel.send_notification = AsyncMock()
        tracer = ProxyTracer(channel)
        await tracer.aflush()

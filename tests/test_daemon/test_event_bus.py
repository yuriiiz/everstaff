import asyncio
import pytest
from everstaff.daemon.event_bus import EventBus
from everstaff.protocols import AgentEvent


@pytest.mark.asyncio
async def test_subscribe_and_publish_targeted():
    bus = EventBus()
    bus.subscribe("agent-a")
    event = AgentEvent(source="test", type="ping", target_agent="agent-a")
    await bus.publish(event)
    received = await bus.wait_for("agent-a", timeout=1.0)
    assert received is not None
    assert received.type == "ping"


@pytest.mark.asyncio
async def test_publish_broadcast():
    bus = EventBus()
    bus.subscribe("agent-a")
    bus.subscribe("agent-b")
    event = AgentEvent(source="test", type="broadcast")
    await bus.publish(event)
    a = await bus.wait_for("agent-a", timeout=1.0)
    b = await bus.wait_for("agent-b", timeout=1.0)
    assert a is not None and a.type == "broadcast"
    assert b is not None and b.type == "broadcast"


@pytest.mark.asyncio
async def test_targeted_not_received_by_others():
    bus = EventBus()
    bus.subscribe("agent-a")
    bus.subscribe("agent-b")
    event = AgentEvent(source="test", type="targeted", target_agent="agent-a")
    await bus.publish(event)
    a = await bus.wait_for("agent-a", timeout=1.0)
    b = await bus.wait_for("agent-b", timeout=0.1)
    assert a is not None
    assert b is None


@pytest.mark.asyncio
async def test_wait_for_timeout_returns_none():
    bus = EventBus()
    bus.subscribe("agent-a")
    result = await bus.wait_for("agent-a", timeout=0.05)
    assert result is None


@pytest.mark.asyncio
async def test_drain():
    bus = EventBus()
    bus.subscribe("agent-a")
    await bus.publish(AgentEvent(source="t", type="e1", target_agent="agent-a"))
    await bus.publish(AgentEvent(source="t", type="e2", target_agent="agent-a"))
    events = bus.drain("agent-a")
    assert len(events) == 2
    assert events[0].type == "e1"
    # Queue should be empty now
    assert bus.drain("agent-a") == []


@pytest.mark.asyncio
async def test_unsubscribe():
    bus = EventBus()
    bus.subscribe("agent-a")
    bus.unsubscribe("agent-a")
    await bus.publish(AgentEvent(source="t", type="e1", target_agent="agent-a"))
    # No queue, nothing received
    result = await bus.wait_for("agent-a", timeout=0.05)
    assert result is None


@pytest.mark.asyncio
async def test_drain_unsubscribed_returns_empty():
    bus = EventBus()
    assert bus.drain("nonexistent") == []

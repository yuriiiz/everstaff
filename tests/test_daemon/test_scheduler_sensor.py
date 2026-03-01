import asyncio
import pytest
from everstaff.daemon.event_bus import EventBus
from everstaff.daemon.sensors.scheduler import SchedulerSensor
from everstaff.schema.autonomy import TriggerConfig


@pytest.mark.asyncio
async def test_interval_trigger_fires_event():
    bus = EventBus()
    bus.subscribe("test-agent")
    trigger = TriggerConfig(id="fast_tick", type="interval", every=1, task="test task")
    sensor = SchedulerSensor(
        triggers=[trigger],
        agent_name="test-agent",
    )
    await sensor.start(bus)
    # Wait for at least one event
    event = await bus.wait_for("test-agent", timeout=3.0)
    await sensor.stop()
    assert event is not None
    assert event.source == "cron"
    assert event.type == "cron.fast_tick"
    assert event.payload["task"] == "test task"
    assert event.target_agent == "test-agent"


@pytest.mark.asyncio
async def test_stop_prevents_further_events():
    bus = EventBus()
    bus.subscribe("test-agent")
    trigger = TriggerConfig(id="tick", type="interval", every=1, task="t")
    sensor = SchedulerSensor(triggers=[trigger], agent_name="test-agent")
    await sensor.start(bus)
    await sensor.stop()
    # Drain anything already queued
    bus.drain("test-agent")
    # Should get nothing new
    event = await bus.wait_for("test-agent", timeout=1.5)
    assert event is None

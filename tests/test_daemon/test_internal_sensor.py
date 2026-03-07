"""Tests for InternalSensor."""
import asyncio
import pytest

from everstaff.daemon.sensors.base import Sensor
from everstaff.daemon.sensors.internal import InternalSensor
from everstaff.daemon.event_bus import EventBus
from everstaff.schema.autonomy import TriggerConfig


@pytest.fixture
def bus():
    b = EventBus()
    b.subscribe("reflector")
    return b


def test_internal_sensor_is_sensor():
    sensor = InternalSensor(triggers=[], agent_name="r")
    assert isinstance(sensor, Sensor)


@pytest.mark.asyncio
async def test_episode_count_fires_at_threshold(bus):
    trigger = TriggerConfig(
        id="self-reflect",
        type="internal",
        condition="episode_count",
        threshold=3,
        task="analyze episodes",
    )
    sensor = InternalSensor(triggers=[trigger], agent_name="reflector")
    await sensor.start(bus)

    # Notify fewer than threshold — no event
    for _ in range(2):
        sensor.notify_episode()
    event = await bus.wait_for("reflector", timeout=0.1)
    assert event is None

    # One more crosses threshold
    sensor.notify_episode()
    event = await asyncio.wait_for(bus.wait_for("reflector", timeout=1), timeout=2)
    assert event is not None
    assert event.source == "internal"
    assert event.type == "internal.self-reflect"
    assert event.payload["condition"] == "episode_count"

    await sensor.stop()


@pytest.mark.asyncio
async def test_counter_resets_after_firing(bus):
    trigger = TriggerConfig(
        id="reflect", type="internal", condition="episode_count",
        threshold=2, task="reflect",
    )
    sensor = InternalSensor(triggers=[trigger], agent_name="reflector")
    await sensor.start(bus)

    # Fire once
    sensor.notify_episode()
    sensor.notify_episode()
    event = await asyncio.wait_for(bus.wait_for("reflector", timeout=1), timeout=2)
    assert event is not None

    # Counter should have reset — one more should not fire
    sensor.notify_episode()
    event = await bus.wait_for("reflector", timeout=0.1)
    assert event is None

    await sensor.stop()

"""Tests for FileWatchSensor."""
import asyncio

import pytest

from everstaff.daemon.event_bus import EventBus
from everstaff.daemon.sensors.base import Sensor
from everstaff.daemon.sensors.file_watch import FileWatchSensor
from everstaff.schema.autonomy import TriggerConfig


@pytest.fixture
def bus():
    b = EventBus()
    b.subscribe("watcher")
    return b


def test_file_watch_sensor_is_sensor():
    sensor = FileWatchSensor(triggers=[], agent_name="w")
    assert isinstance(sensor, Sensor)


@pytest.mark.asyncio
async def test_file_watch_detects_change(bus, tmp_path):
    watched = tmp_path / "config"
    watched.mkdir()

    trigger = TriggerConfig(
        id="cfg-watch",
        type="file_watch",
        task="config changed",
        watch_paths=[str(watched)],
    )
    sensor = FileWatchSensor(triggers=[trigger], agent_name="watcher")
    await sensor.start(bus)

    # Give watcher time to start
    await asyncio.sleep(0.3)

    # Create a file to trigger watch
    (watched / "test.yaml").write_text("key: value")

    # Wait for event
    event = await asyncio.wait_for(bus.wait_for("watcher", timeout=5), timeout=6)
    assert event is not None
    assert event.source == "file_watch"
    assert event.type == "file_watch.cfg-watch"
    assert event.target_agent == "watcher"

    await sensor.stop()

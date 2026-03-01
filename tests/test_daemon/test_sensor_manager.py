import pytest
from everstaff.daemon.event_bus import EventBus
from everstaff.daemon.sensor_manager import SensorManager


class FakeSensor:
    def __init__(self):
        self.started = False
        self.stopped = False

    async def start(self, event_bus):
        self.started = True

    async def stop(self):
        self.stopped = True


@pytest.mark.asyncio
async def test_start_all():
    bus = EventBus()
    mgr = SensorManager(bus)
    s1 = FakeSensor()
    s2 = FakeSensor()
    mgr.register(s1)
    mgr.register(s2)
    await mgr.start_all()
    assert s1.started and s2.started


@pytest.mark.asyncio
async def test_stop_all():
    bus = EventBus()
    mgr = SensorManager(bus)
    s1 = FakeSensor()
    mgr.register(s1)
    await mgr.start_all()
    await mgr.stop_all()
    assert s1.stopped


@pytest.mark.asyncio
async def test_unregister_for_agent():
    bus = EventBus()
    mgr = SensorManager(bus)
    s1 = FakeSensor()
    mgr.register(s1, agent_name="agent-a")
    await mgr.start_all()
    await mgr.unregister_for("agent-a")
    assert s1.stopped

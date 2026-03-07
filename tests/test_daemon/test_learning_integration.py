"""Integration test: InternalSensor triggers learning cycle in ThinkEngine."""
import asyncio
import pytest

from everstaff.daemon.event_bus import EventBus
from everstaff.daemon.sensors.internal import InternalSensor
from everstaff.schema.autonomy import TriggerConfig


@pytest.mark.asyncio
async def test_episode_accumulation_triggers_reflection_event():
    """After N episodes, InternalSensor fires a reflection event."""
    bus = EventBus()
    bus.subscribe("learner")

    trigger = TriggerConfig(
        id="reflect", type="internal", condition="episode_count",
        threshold=3, task="analyze recent episodes",
    )
    sensor = InternalSensor(triggers=[trigger], agent_name="learner")
    await sensor.start(bus)

    for _ in range(3):
        sensor.notify_episode()

    event = await asyncio.wait_for(bus.wait_for("learner", timeout=1), timeout=2)
    assert event is not None
    assert event.source == "internal"
    assert event.type == "internal.reflect"
    assert event.payload["task"] == "analyze recent episodes"
    assert event.payload["condition"] == "episode_count"

    # Counter should have reset
    sensor.notify_episode()
    no_event = await bus.wait_for("learner", timeout=0.1)
    assert no_event is None

    await sensor.stop()


@pytest.mark.asyncio
async def test_mutation_tools_block_permission_changes():
    """Self-mutation tools hard-reject permission mutations."""
    from everstaff.daemon.mutation_tools import validate_no_permission_mutation, PermissionMutationForbidden

    for key in ("permissions", "allow", "deny"):
        with pytest.raises(PermissionMutationForbidden):
            validate_no_permission_mutation({key: "anything"})

    for key in ("skills", "instructions", "mcp_servers", "autonomy"):
        validate_no_permission_mutation({key: "anything"})

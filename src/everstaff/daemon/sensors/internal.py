"""InternalSensor — monitors daemon-internal state and emits events at thresholds."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from everstaff.daemon.sensors.base import Sensor

if TYPE_CHECKING:
    from everstaff.daemon.event_bus import EventBus
    from everstaff.schema.autonomy import TriggerConfig

logger = logging.getLogger(__name__)


class InternalSensor(Sensor):
    """Counts internal events (episodes, errors) and fires when thresholds are met."""

    def __init__(self, triggers: list[TriggerConfig], agent_name: str) -> None:
        self._triggers = [t for t in triggers if t.type == "internal"]
        self._agent_name = agent_name
        self._bus: EventBus | None = None
        self._episode_count: int = 0

    async def start(self, event_bus: EventBus) -> None:
        self._bus = event_bus
        self._episode_count = 0
        logger.info("[InternalSensor:%s] Started with %d trigger(s)", self._agent_name, len(self._triggers))

    def notify_episode(self) -> None:
        """Called by AgentLoop after each episode is recorded."""
        self._episode_count += 1
        for trigger in self._triggers:
            if trigger.condition == "episode_count" and self._episode_count >= trigger.threshold:
                self._episode_count = 0
                self._fire(trigger)

    def _fire(self, trigger: TriggerConfig) -> None:
        if not self._bus:
            return
        import asyncio
        from everstaff.protocols import AgentEvent

        event = AgentEvent(
            source="internal",
            type=f"internal.{trigger.id}",
            payload={
                "task": trigger.task,
                "trigger_id": trigger.id,
                "condition": trigger.condition,
            },
            target_agent=self._agent_name,
        )
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._bus.publish(event))
        except RuntimeError:
            logger.warning("[InternalSensor:%s] No running event loop", self._agent_name)

    async def stop(self) -> None:
        self._bus = None
        self._episode_count = 0
        logger.info("[InternalSensor:%s] Stopped", self._agent_name)

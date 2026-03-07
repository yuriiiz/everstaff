"""SensorManager — lifecycle manager for all sensors."""
from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from everstaff.daemon.event_bus import EventBus

logger = logging.getLogger(__name__)


class SensorManager:
    def __init__(self, event_bus: "EventBus") -> None:
        self._bus = event_bus
        self._sensors: list[tuple[Any, str | None]] = []  # (sensor, agent_name)

    def register(self, sensor: Any, agent_name: str | None = None) -> None:
        self._sensors.append((sensor, agent_name))
        logger.info("registered sensor agent=%s total=%d",
                     agent_name or '(global)', len(self._sensors))

    async def start_all(self) -> None:
        logger.info("starting all sensors count=%d", len(self._sensors))
        for sensor, name in self._sensors:
            await sensor.start(self._bus)
            logger.debug("started sensor agent=%s", name or '(global)')

    async def stop_all(self) -> None:
        count = len(self._sensors)
        logger.info("stopping all sensors count=%d", count)
        for sensor, name in self._sensors:
            await sensor.stop()
            logger.debug("stopped sensor agent=%s", name or '(global)')
        self._sensors.clear()
        logger.info("all sensors stopped and cleared count=%d", count)

    async def unregister_for(self, agent_name: str) -> None:
        remaining = []
        stopped = 0
        for sensor, name in self._sensors:
            if name == agent_name:
                await sensor.stop()
                stopped += 1
            else:
                remaining.append((sensor, name))
        self._sensors = remaining
        if stopped:
            logger.info("unregistered sensors count=%d agent=%s", stopped, agent_name)

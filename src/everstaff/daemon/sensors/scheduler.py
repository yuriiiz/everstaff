"""SchedulerSensor — converts cron/interval triggers into AgentEvents."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from everstaff.daemon.sensors.base import Sensor

if TYPE_CHECKING:
    from everstaff.daemon.event_bus import EventBus
    from everstaff.schema.autonomy import TriggerConfig

logger = logging.getLogger(__name__)


def _parse_cron(expression: str) -> dict:
    """Parse '0 9 * * *' into APScheduler cron kwargs."""
    parts = expression.strip().split()
    if len(parts) != 5:
        raise ValueError(f"Invalid cron expression: {expression!r}")
    return {
        "minute": parts[0],
        "hour": parts[1],
        "day": parts[2],
        "month": parts[3],
        "day_of_week": parts[4],
    }


class SchedulerSensor(Sensor):
    """Converts cron/interval TriggerConfigs into AgentEvents on the EventBus.

    Uses APScheduler (v3) AsyncIOScheduler under the hood to fire jobs
    that publish AgentEvent instances with source="cron".
    """

    def __init__(self, triggers: list[TriggerConfig], agent_name: str) -> None:
        self._triggers = triggers
        self._agent_name = agent_name
        self._scheduler = None
        self._bus: EventBus | None = None

    async def start(self, event_bus: EventBus) -> None:
        """Register all triggers with APScheduler and start the scheduler."""
        from apscheduler.schedulers.asyncio import AsyncIOScheduler

        self._bus = event_bus
        self._scheduler = AsyncIOScheduler()

        for trigger in self._triggers:
            if trigger.type == "cron" and trigger.schedule:
                self._scheduler.add_job(
                    self._emit,
                    "cron",
                    **_parse_cron(trigger.schedule),
                    args=[trigger],
                    id=f"{self._agent_name}-{trigger.id}",
                )
                logger.info("registered cron job agent=%s name=%s expr=%s",
                             self._agent_name, trigger.id, trigger.schedule)
            elif trigger.type == "interval" and trigger.every > 0:
                self._scheduler.add_job(
                    self._emit,
                    "interval",
                    seconds=trigger.every,
                    args=[trigger],
                    id=f"{self._agent_name}-{trigger.id}",
                )
                logger.info("registered interval job agent=%s name=%s every=%ds",
                             self._agent_name, trigger.id, trigger.every)
        self._scheduler.start()
        logger.info("scheduler started agent=%s jobs=%d",
                     self._agent_name, len(self._triggers))

    async def _emit(self, trigger: TriggerConfig) -> None:
        """Publish an AgentEvent for the given trigger."""
        from everstaff.protocols import AgentEvent

        event = AgentEvent(
            source="cron",
            type=f"cron.{trigger.id}",
            payload={"task": trigger.task, "trigger_id": trigger.id},
            target_agent=self._agent_name,
        )
        await self._bus.publish(event)
        logger.info("fired trigger agent=%s name=%s task=%s",
                     self._agent_name, trigger.id, trigger.task[:80] if trigger.task else '-')

    async def stop(self) -> None:
        """Shut down the APScheduler, preventing further job execution."""
        if self._scheduler:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
            logger.info("scheduler stopped agent=%s", self._agent_name)

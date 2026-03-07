"""FileWatchSensor — monitors file/directory changes using watchfiles."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from everstaff.daemon.sensors.base import Sensor

if TYPE_CHECKING:
    from everstaff.daemon.event_bus import EventBus
    from everstaff.schema.autonomy import TriggerConfig

logger = logging.getLogger(__name__)

_CHANGE_LABELS = {1: "added", 2: "modified", 3: "deleted"}


class FileWatchSensor(Sensor):
    """Watches file paths and publishes AgentEvents on changes."""

    def __init__(self, triggers: list[TriggerConfig], agent_name: str) -> None:
        self._triggers = [t for t in triggers if t.type == "file_watch"]
        self._agent_name = agent_name
        self._bus: EventBus | None = None
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

    async def start(self, event_bus: EventBus) -> None:
        if not self._triggers:
            return
        self._bus = event_bus
        self._stop_event.clear()
        self._task = asyncio.create_task(self._watch_loop(), name=f"file-watch-{self._agent_name}")
        logger.info("[FileWatchSensor:%s] Started watching %d trigger(s)", self._agent_name, len(self._triggers))

    async def _watch_loop(self) -> None:
        from watchfiles import awatch

        path_to_trigger: dict[str, TriggerConfig] = {}
        all_paths: list[Path] = []
        for trigger in self._triggers:
            for p in trigger.watch_paths:
                resolved = Path(p).resolve()
                path_to_trigger[str(resolved)] = trigger
                all_paths.append(resolved)

        try:
            async for changes in awatch(*all_paths, stop_event=self._stop_event):
                for change_type, changed_path in changes:
                    label = _CHANGE_LABELS.get(change_type, "unknown")
                    trigger = self._find_trigger(changed_path, path_to_trigger)
                    if trigger and self._bus:
                        from everstaff.protocols import AgentEvent

                        event = AgentEvent(
                            source="file_watch",
                            type=f"file_watch.{trigger.id}",
                            payload={
                                "task": trigger.task,
                                "trigger_id": trigger.id,
                                "changed_path": changed_path,
                                "change_type": label,
                            },
                            target_agent=self._agent_name,
                        )
                        await self._bus.publish(event)
        except asyncio.CancelledError:
            pass

    def _find_trigger(self, changed_path: str, path_to_trigger: dict[str, TriggerConfig]) -> TriggerConfig | None:
        changed = Path(changed_path).resolve()
        for watched_str, trigger in path_to_trigger.items():
            watched = Path(watched_str)
            if changed == watched or watched in changed.parents:
                return trigger
        return None

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        self._bus = None
        logger.info("[FileWatchSensor:%s] Stopped", self._agent_name)

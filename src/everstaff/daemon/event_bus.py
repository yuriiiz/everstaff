"""EventBus — in-process event routing via asyncio.Queue."""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from everstaff.protocols import AgentEvent

logger = logging.getLogger(__name__)


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, asyncio.Queue[AgentEvent]] = {}

    def subscribe(self, agent_name: str) -> asyncio.Queue:
        if agent_name not in self._subscribers:
            self._subscribers[agent_name] = asyncio.Queue()
            logger.info("[EventBus] Subscribed: '%s'", agent_name)
        return self._subscribers[agent_name]

    def unsubscribe(self, agent_name: str) -> None:
        removed = self._subscribers.pop(agent_name, None)
        if removed is not None:
            logger.info("[EventBus] Unsubscribed: '%s'", agent_name)

    async def publish(self, event: "AgentEvent") -> None:
        if event.target_agent:
            q = self._subscribers.get(event.target_agent)
            if q:
                await q.put(event)
                logger.debug("[EventBus] Published %s:%s → '%s'", event.source, event.type, event.target_agent)
            else:
                logger.warning("[EventBus] No subscriber for target '%s' — event %s:%s dropped",
                               event.target_agent, event.source, event.type)
        else:
            for name, q in self._subscribers.items():
                await q.put(event)
            logger.debug("[EventBus] Broadcast %s:%s → %d subscriber(s)",
                          event.source, event.type, len(self._subscribers))

    async def wait_for(
        self, agent_name: str, timeout: float | None = None,
    ) -> "AgentEvent | None":
        q = self._subscribers.get(agent_name)
        if not q:
            return None
        try:
            return await asyncio.wait_for(q.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    def drain(self, agent_name: str) -> list["AgentEvent"]:
        q = self._subscribers.get(agent_name)
        if not q:
            return []
        events: list[AgentEvent] = []
        while not q.empty():
            try:
                events.append(q.get_nowait())
            except asyncio.QueueEmpty:
                break
        if events:
            logger.debug("[EventBus] Drained %d event(s) for '%s'", len(events), agent_name)
        return events

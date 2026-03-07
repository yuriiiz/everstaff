"""WebhookSensor — receives external HTTP push events via FastAPI endpoint."""
from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from everstaff.daemon.sensors.base import Sensor

if TYPE_CHECKING:
    from everstaff.daemon.event_bus import EventBus
    from everstaff.schema.autonomy import TriggerConfig

logger = logging.getLogger(__name__)


class WebhookSensor(Sensor):
    """Registers POST /api/daemon/webhook/{agent_uuid} on the FastAPI app."""

    def __init__(
        self,
        triggers: list[TriggerConfig],
        agent_name: str,
        agent_uuid: str,
        app: Any,
    ) -> None:
        self._triggers = {t.id: t for t in triggers if t.type == "webhook"}
        self._agent_name = agent_name
        self._agent_uuid = agent_uuid
        self._app = app
        self._bus: EventBus | None = None
        self._route_path: str | None = None

    async def start(self, event_bus: EventBus) -> None:
        if not self._triggers:
            return
        self._bus = event_bus
        self._route_path = f"/api/daemon/webhook/{self._agent_uuid}"

        async def _endpoint(request: Any) -> dict:
            from starlette.requests import Request
            body: dict = {}
            if isinstance(request, Request):
                body = await request.json()
            trigger_id = body.pop("trigger_id", None)
            if trigger_id and trigger_id in self._triggers:
                await self.handle_webhook(trigger_id=trigger_id, payload=body)
            elif len(self._triggers) == 1:
                tid = next(iter(self._triggers))
                await self.handle_webhook(trigger_id=tid, payload=body)
            else:
                await self.handle_webhook(trigger_id="unknown", payload=body)
            return {"status": "accepted"}

        self._app.add_api_route(
            self._route_path, _endpoint, methods=["POST"],
            name=f"webhook_{self._agent_uuid}",
        )
        logger.info("[WebhookSensor:%s] Registered %s", self._agent_name, self._route_path)

    async def handle_webhook(self, *, trigger_id: str, payload: dict) -> None:
        from everstaff.protocols import AgentEvent
        trigger = self._triggers.get(trigger_id)
        task = trigger.task if trigger else ""
        event = AgentEvent(
            source="webhook",
            type=f"webhook.{trigger_id}",
            payload={**payload, "task": task, "trigger_id": trigger_id},
            target_agent=self._agent_name,
        )
        if self._bus:
            await self._bus.publish(event)

    async def stop(self) -> None:
        self._bus = None
        logger.info("[WebhookSensor:%s] Stopped", self._agent_name)

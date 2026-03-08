"""LarkMessageHandler — Channel entry layer for Lark messages.

Subscribes to EventBus lark_message events.
Sends agent selection card -> user selects -> retract card -> create session.
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Callable, Awaitable, TYPE_CHECKING

if TYPE_CHECKING:
    from everstaff.channels.lark_adapter import LarkChannelAdapter
    from everstaff.core.event_bus import EventBus

logger = logging.getLogger(__name__)

_SUBSCRIBER = "__lark_message_handler__"


class LarkMessageHandler:
    """Handles incoming Lark messages: agent selection -> session creation."""

    def __init__(
        self,
        adapter: "LarkChannelAdapter",
        event_bus: "EventBus",
        agents_dir: str,
        session_create_fn: Callable[..., Awaitable[str]] | None = None,
        hitl_router: Any = None,
    ) -> None:
        self._adapter = adapter
        self._bus = event_bus
        self._agents_dir = Path(agents_dir).expanduser().resolve()
        self._session_create_fn = session_create_fn
        self._hitl_router = hitl_router
        self._task: asyncio.Task | None = None
        self._pending_selections: dict[str, dict[str, str]] = {}

    async def start(self) -> None:
        self._bus.subscribe(_SUBSCRIBER)
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("LarkMessageHandler started")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
        self._bus.unsubscribe(_SUBSCRIBER)
        logger.info("LarkMessageHandler stopped")

    async def _poll_loop(self) -> None:
        while True:
            try:
                event = await self._bus.wait_for(_SUBSCRIBER, timeout=60)
                if event is None:
                    continue
                if event.type != "lark_message":
                    continue
                await self._handle_message(event)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("LarkMessageHandler error: %s", exc, exc_info=True)

    async def _handle_message(self, event: Any) -> None:
        payload = event.payload
        chat_id = payload.get("chat_id", "")
        sender = payload.get("sender_open_id", "")
        text = payload.get("content", "")

        if not chat_id or not text.strip():
            return

        agents = self._list_agents()
        if not agents:
            await self._adapter.send_text(chat_id, "No agents available.")
            return

        card = self._build_agent_selection_card(agents, sender, text)
        mid = await self._adapter.send_card(chat_id, card)
        if mid:
            self._pending_selections[mid] = {
                "sender_open_id": sender,
                "chat_id": chat_id,
                "user_input": text,
            }

    def _list_agents(self) -> list[dict[str, str]]:
        from everstaff.utils.yaml_loader import load_yaml

        agents = []
        if not self._agents_dir.exists():
            return agents
        for f in sorted(self._agents_dir.glob("*.yaml")):
            try:
                spec = load_yaml(str(f))
                agents.append(
                    {
                        "name": spec.get("agent_name", f.stem),
                        "uuid": spec.get("uuid", ""),
                        "description": spec.get("description", ""),
                    }
                )
            except Exception:
                continue
        return agents

    def _build_agent_selection_card(
        self,
        agents: list[dict],
        sender_open_id: str,
        user_input: str,
    ) -> dict:
        elements = [
            {
                "tag": "markdown",
                "content": f"**Message:** {user_input[:200]}\n\nSelect an agent:",
            }
        ]
        actions = []
        for i, agent in enumerate(agents):
            actions.append(
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": agent["name"]},
                    "type": "primary" if i == 0 else "default",
                    "value": json.dumps(
                        {
                            "type": "agent_select",
                            "agent_name": agent["name"],
                            "agent_uuid": agent.get("uuid", ""),
                            "sender_open_id": sender_open_id,
                            "user_input": user_input,
                        }
                    ),
                }
            )
        elements.append({"tag": "action", "actions": actions})

        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": "Select Agent"},
                "template": "blue",
            },
            "elements": elements,
        }

    async def on_agent_selected(
        self,
        message_id: str,
        value: dict,
        operator_open_id: str,
    ) -> dict:
        """Called when user clicks an agent button on the selection card."""
        expected_sender = value.get("sender_open_id", "")
        if expected_sender and operator_open_id != expected_sender:
            return {
                "toast": {
                    "type": "warning",
                    "content": "Only the original sender can select.",
                }
            }

        pending = self._pending_selections.pop(message_id, None)
        chat_id = pending["chat_id"] if pending else ""
        agent_name = value.get("agent_name", "")
        user_input = value.get("user_input", "")

        # Retract the selection card
        try:
            await self._adapter.delete_message(message_id)
        except Exception as exc:
            logger.warning(
                "failed to retract selection card mid=%s err=%s", message_id, exc
            )

        if self._session_create_fn and agent_name:
            source_info = {
                "source_type": "lark",
                "chat_id": chat_id,
                "sender_open_id": operator_open_id,
            }
            session_id = await self._session_create_fn(
                agent_name, user_input, source_info
            )

            if self._hitl_router:
                self._hitl_router.set_session_source(
                    session_id, "lark", {"chat_id": chat_id}
                )

            return {
                "toast": {
                    "type": "success",
                    "content": f"Session started with {agent_name}",
                }
            }

        return {"toast": {"type": "error", "content": "Failed to create session"}}

    async def deliver_result(
        self, session_id: str, chat_id: str, result: str
    ) -> None:
        """Send session result back to Lark chat. Short -> text, long -> card."""
        if not result or not chat_id:
            return
        THRESHOLD = 500
        if len(result) <= THRESHOLD:
            await self._adapter.send_text(chat_id, result)
        else:
            card = {
                "config": {"wide_screen_mode": True},
                "header": {
                    "title": {"tag": "plain_text", "content": "Agent Result"},
                    "template": "green",
                },
                "elements": [
                    {"tag": "markdown", "content": result[:2000]},
                ],
            }
            if len(result) > 2000:
                card["elements"].append(
                    {
                        "tag": "markdown",
                        "content": f"*... ({len(result)} chars total, truncated)*",
                    }
                )
            await self._adapter.send_card(chat_id, card)

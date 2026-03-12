"""LarkMessageHandler — Channel entry layer for Lark messages.

Subscribes to EventBus lark_message events.
Sends agent selection card -> user selects -> retract card -> create session.
Follow-up messages in conversation groups are routed to the existing session.
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
        session_continue_fn: Callable[..., Awaitable[None]] | None = None,
        hitl_router: Any = None,
        bot_name: str = "Agent",
    ) -> None:
        self._adapter = adapter
        self._bus = event_bus
        self._agents_dir = Path(agents_dir).expanduser().resolve()
        self._session_create_fn = session_create_fn
        self._session_continue_fn = session_continue_fn
        self._hitl_router = hitl_router
        self._bot_name = bot_name
        self._task: asyncio.Task | None = None
        self._pending_selections: dict[str, dict[str, str]] = {}
        # chat_id -> conversation group state (session_id, agent_name, ...)
        self._conversation_groups: dict[str, dict[str, str]] = {}

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
        message_id = payload.get("message_id", "")

        if not chat_id or not text.strip():
            return

        # Handle /help command
        if text.strip() == "/help":
            await self._send_help(chat_id)
            return

        # Check if this is a known conversation group — only the owner gets free pass
        conv = self._conversation_groups.get(chat_id)
        if conv and sender == conv.get("open_id"):
            logger.info("routing to conversation group chat_id=%s session=%s text=%s",
                        chat_id, conv.get("session_id", "?")[:8], text[:80])
            if self._session_continue_fn:
                await self._session_continue_fn(
                    session_id=conv["session_id"],
                    agent_name=conv.get("agent_name", ""),
                    user_input=text,
                    chat_id=chat_id,
                    sender_open_id=sender,
                )
            else:
                logger.warning("conversation group message dropped: no session_continue_fn chat_id=%s", chat_id)
            return

        # Handle /new command: reset conversation
        if text.strip().lower() == "/new":
            self._conversation_groups.pop(chat_id, None)
            # Fall through to agent selection below

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

    async def _send_help(self, chat_id: str) -> None:
        agents = self._list_agents()
        agent_lines = "\n".join(
            f"  - **{a['name']}**: {a.get('description', '')}" for a in agents
        )
        help_text = (
            "**Supported Commands**\n\n"
            "/help - Show this help message\n"
            "/new - Start a new conversation\n\n"
            "**How to use**\n"
            "Send any message to start a session. "
            "You will be prompted to select an agent, "
            "then a new group chat will be created for the conversation.\n\n"
            f"**Available Agents**\n{agent_lines}"
        )
        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": "Help"},
                "template": "turquoise",
            },
            "elements": [{"tag": "markdown", "content": help_text}],
        }
        await self._adapter.send_card(chat_id, card)

    def _list_agents(self) -> list[dict[str, str]]:
        from everstaff.utils.yaml_loader import load_yaml

        agents_by_uuid: dict[str, dict[str, str]] = {}

        # Only collect user agents (exclude builtins)
        if self._agents_dir.exists():
            for f in sorted(self._agents_dir.glob("*.yaml")):
                try:
                    spec = load_yaml(str(f))
                    uid = spec.get("uuid", f.stem)
                    if spec.get("source") == "builtin":
                        continue
                    agents_by_uuid[uid] = {
                        "name": spec.get("agent_name", f.stem),
                        "uuid": uid,
                        "description": spec.get("description", ""),
                    }
                except Exception:
                    continue

        return list(agents_by_uuid.values())

    def _build_agent_selection_card(
        self,
        agents: list[dict],
        sender_open_id: str,
        user_input: str,
    ) -> dict:
        elements = [
            {
                "tag": "markdown",
                "content": f"**Message:** {user_input[:200]}\n\nSelect an agent to start a session:",
            }
        ]
        for agent in agents:
            desc = agent.get("description", "")
            agent_info = f"**{agent['name']}**"
            if desc:
                agent_info += f"\n{desc[:100]}"
            elements.append({
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "Start Session"},
                        "type": "primary",
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
                ],
                "layout": "bisected",
            })
            elements.insert(-1, {"tag": "markdown", "content": agent_info})

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
        """Called when user clicks an agent button on the selection card.

        Creates a new group chat for the session conversation.
        """
        expected_sender = value.get("sender_open_id", "")
        if expected_sender and operator_open_id != expected_sender:
            return {
                "toast": {
                    "type": "warning",
                    "content": "Only the original sender can select.",
                }
            }

        pending = self._pending_selections.pop(message_id, None)
        agent_name = value.get("agent_name", "")
        user_input = value.get("user_input", "")

        # Retract the selection card
        try:
            await self._adapter.delete_message(message_id)
        except Exception as exc:
            logger.warning(
                "failed to retract selection card mid=%s err=%s", message_id, exc
            )

        if not (self._session_create_fn and agent_name):
            return {"toast": {"type": "error", "content": "Failed to create session"}}

        # Create a new group chat for this session
        try:
            username = await self._adapter.resolve_username(operator_open_id)
            group_name = f"{self._bot_name} - {username} - {agent_name}"
            new_chat_id = await self._adapter.create_chat_group(group_name, operator_open_id)
            if not new_chat_id:
                return {"toast": {"type": "error", "content": "Failed to create group"}}
            await self._adapter.add_chat_members(new_chat_id, [operator_open_id])
        except Exception as exc:
            logger.error("on_agent_selected create group failed err=%s", exc, exc_info=True)
            return {"toast": {"type": "error", "content": f"Failed to create group: {exc}"}}

        source_info = {
            "source_type": "lark",
            "chat_id": new_chat_id,
            "sender_open_id": operator_open_id,
        }
        session_id = await self._session_create_fn(
            agent_name, user_input, source_info
        )

        # Register this group as a conversation group for follow-up messages
        self._conversation_groups[new_chat_id] = {
            "session_id": session_id,
            "agent_name": agent_name,
            "agent_uuid": value.get("agent_uuid", ""),
            "open_id": operator_open_id,
        }
        logger.info("registered conversation group chat_id=%s session=%s agent=%s",
                     new_chat_id, session_id[:8], agent_name)

        return {
            "toast": {
                "type": "success",
                "content": f"Session started with {agent_name}",
            }
        }

    async def deliver_result(
        self, session_id: str, chat_id: str, result: str
    ) -> None:
        """Send session result back to Lark chat as markdown card."""
        if not result or not chat_id:
            return
        result = result.strip()
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

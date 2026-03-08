"""LarkWsConnection — one WebSocket per app_id, shared across channels.

Handles:
- WebSocket lifecycle (connect, reconnect via lark-oapi SDK)
- Card action dispatch (by value.type)
- Message reception (p2_im_message_receive_v1)
- HTTP helpers (get_access_token, send_card, update_card)
"""
from __future__ import annotations

import asyncio
import base64
import http
import json
import logging
import threading
import time
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from everstaff.channels.manager import ChannelManager
    from everstaff.daemon.event_bus import EventBus

logger = logging.getLogger(__name__)

_DOMAIN_TO_API_BASE = {
    "feishu": "https://open.feishu.cn/open-apis",
    "lark": "https://open.larksuite.com/open-apis",
}


class LarkWsConnection:
    """Manages a single WebSocket connection to Feishu/Lark for one app_id.

    Multiple LarkWsChannel instances can share the same connection.
    Incoming events are dispatched by type:
    - Card actions with type=hitl → channel_manager.resolve()
    - Card actions with other types → EventBus
    - User messages → EventBus as AgentEvent(type="lark_message")
    """

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        domain: str = "feishu",
    ) -> None:
        self._app_id = app_id
        self._app_secret = app_secret
        self._domain = domain
        self._api_base = _DOMAIN_TO_API_BASE.get(domain, _DOMAIN_TO_API_BASE["feishu"])

        # Injected after construction
        self._channel_manager: ChannelManager | None = None
        self._event_bus: EventBus | None = None

        # chat_id → agent_name routing for incoming messages
        self._chat_to_agent: dict[str, str] = {}

        self._started: bool = False
        self._ws_thread: threading.Thread | None = None
        self._app_loop: asyncio.AbstractEventLoop | None = None

    # ── Chat routing ─────────────────────────────────────────────

    def register_chat_route(self, chat_id: str, agent_name: str) -> None:
        """Register a chat_id → agent_name mapping for message routing."""
        self._chat_to_agent[chat_id] = agent_name
        logger.info("registered chat route chat_id=%s agent=%s app=%s", chat_id, agent_name, self._app_id)

    def _resolve_agent(self, chat_id: str) -> str | None:
        """Resolve which agent handles messages from this chat."""
        return self._chat_to_agent.get(chat_id)

    # ── Card value parsing ───────────────────────────────────────

    @staticmethod
    def _parse_card_value(value: dict) -> tuple[str, dict]:
        """Parse a card action value dict. Returns (action_type, value_dict)."""
        action_type = value.get("type", "hitl")
        return action_type, value

    # ── HTTP helpers ─────────────────────────────────────────────

    async def get_access_token(self) -> str:
        import aiohttp
        url = f"{self._api_base}/auth/v3/tenant_access_token/internal"
        async with aiohttp.ClientSession() as s:
            async with s.post(url, json={"app_id": self._app_id, "app_secret": self._app_secret}) as r:
                return (await r.json())["tenant_access_token"]

    async def send_card(self, chat_id: str, card: dict) -> str:
        """Send an interactive card to a specific chat. Returns message_id."""
        import aiohttp
        token = await self.get_access_token()
        url = f"{self._api_base}/im/v1/messages?receive_id_type=chat_id"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        body = {"receive_id": chat_id, "msg_type": "interactive", "content": json.dumps(card)}
        logger.info("POST url=%s chat_id=%s", url, chat_id)
        async with aiohttp.ClientSession() as s:
            async with s.post(url, headers=headers, json=body) as r:
                data = await r.json()
                mid = data.get("data", {}).get("message_id", "")
                if not mid:
                    logger.error("send_card failed code=%s msg=%s", data.get("code"), data.get("msg"))
                return mid

    async def update_card(self, message_id: str, card: dict) -> None:
        """Update an existing interactive card."""
        import aiohttp
        token = await self.get_access_token()
        url = f"{self._api_base}/im/v1/messages/{message_id}"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        body = {"msg_type": "interactive", "content": json.dumps(card)}
        async with aiohttp.ClientSession() as s:
            async with s.patch(url, headers=headers, json=body) as r:
                resp_data = await r.json()
                if resp_data.get("code", 0) != 0:
                    logger.error("update_card failed code=%s msg=%s mid=%s",
                                 resp_data.get("code"), resp_data.get("msg"), message_id)
                else:
                    logger.info("update_card status=%s mid=%s", r.status, message_id)

    # ── Card action handler ──────────────────────────────────────

    async def _handle_card_action(self, data: Any) -> dict:
        """Dispatch a card action event by value.type."""
        event = getattr(data, "event", data)
        action = getattr(event, "action", None)
        if action is None:
            logger.warning("card action: no action field")
            return {}

        raw_value = getattr(action, "value", None)
        if isinstance(raw_value, str):
            try:
                value = json.loads(raw_value)
            except (json.JSONDecodeError, TypeError):
                value = {}
        elif isinstance(raw_value, dict):
            value = raw_value
        else:
            value = {}

        # Extract operator
        operator = getattr(event, "operator", None)
        open_id = getattr(operator, "open_id", "lark_user") if operator else "lark_user"
        open_id = open_id or "lark_user"

        action_type, parsed = self._parse_card_value(value)
        logger.info("card action type=%s open_id=%s value=%s", action_type, open_id, parsed)

        if action_type == "hitl":
            return await self._handle_hitl_action(parsed, open_id)
        else:
            if self._event_bus is not None:
                from everstaff.protocols import AgentEvent
                await self._event_bus.publish(AgentEvent(
                    type="lark_card_action",
                    source=self._app_id,
                    payload={"action_type": action_type, "open_id": open_id, **parsed},
                ))
            else:
                logger.warning("non-hitl card action dropped: event_bus not injected action_type=%s", action_type)
            return {"toast": {"type": "success", "content": "OK"}}

    async def _handle_hitl_action(self, value: dict, resolved_by: str) -> dict:
        """Handle HITL card action: resolve via channel_manager."""
        hitl_id = value.get("hitl_id", "")
        decision = value.get("decision", "")

        if not hitl_id or not decision:
            logger.warning("hitl action: missing hitl_id=%s or decision=%s", hitl_id, decision)
            return {}

        if decision == "__input__":
            raw_form = value.get("form_value")
            if isinstance(raw_form, str):
                try:
                    form_dict = json.loads(raw_form)
                except (json.JSONDecodeError, TypeError):
                    form_dict = {}
            elif isinstance(raw_form, dict):
                form_dict = raw_form
            else:
                form_dict = {}
            decision = form_dict.get("user_input", "")

        grant_scope = value.get("grant_scope")
        permission_pattern = value.get("permission_pattern")

        logger.info("hitl action hitl_id=%s decision=%r by=%s", hitl_id, decision, resolved_by)

        if self._channel_manager is None or self._app_loop is None:
            logger.warning(
                "hitl action dropped: channel_manager not injected hitl_id=%s decision=%r",
                hitl_id, decision,
            )
            return {"toast": {"type": "error", "content": "System not ready, please retry"}}

        from everstaff.protocols import HitlResolution
        from datetime import datetime, timezone
        resolution = HitlResolution(
            decision=decision,
            resolved_at=datetime.now(timezone.utc),
            resolved_by=resolved_by,
            grant_scope=grant_scope,
            permission_pattern=permission_pattern,
        )
        asyncio.run_coroutine_threadsafe(
            self._channel_manager.resolve(hitl_id, resolution),
            self._app_loop,
        )

        return {"toast": {"type": "success", "content": f"Decision: {decision}"}}

    # ── Message handler ──────────────────────────────────────────

    async def _handle_message(self, data: Any) -> None:
        """Handle an incoming user message: publish to EventBus."""
        event = getattr(data, "event", data)
        message = getattr(event, "message", None)
        sender = getattr(event, "sender", None)
        if message is None:
            logger.warning("message event: no message field")
            return

        chat_id = getattr(message, "chat_id", "")
        message_id = getattr(message, "message_id", "")
        msg_type = getattr(message, "message_type", "text")
        content_raw = getattr(message, "content", "{}")
        sender_open_id = getattr(getattr(sender, "sender_id", None), "open_id", "") if sender else ""

        try:
            content = json.loads(content_raw) if isinstance(content_raw, str) else content_raw
        except (json.JSONDecodeError, TypeError):
            content = {"text": str(content_raw)}

        text = content.get("text", "") if isinstance(content, dict) else str(content)

        target_agent = self._resolve_agent(chat_id)
        logger.info("message chat_id=%s sender=%s agent=%s text=%s",
                     chat_id, sender_open_id, target_agent or "?", text[:80])

        if self._event_bus is not None:
            from everstaff.protocols import AgentEvent
            await self._event_bus.publish(AgentEvent(
                type="lark_message",
                source=self._app_id,
                payload={
                    "chat_id": chat_id,
                    "sender_open_id": sender_open_id,
                    "content": text,
                    "message_type": msg_type,
                    "message_id": message_id,
                },
                target_agent=target_agent,
            ))

    # ── WS client setup ─────────────────────────────────────────

    def _build_ws_client(self, loop: asyncio.AbstractEventLoop):
        """Build lark-oapi WSClient with card action + message handlers."""
        import lark_oapi as lark
        from lark_oapi.event.callback.model.p2_card_action_trigger import P2CardActionTrigger
        from lark_oapi.ws.enum import MessageType
        from lark_oapi.ws.const import (
            HEADER_TYPE, HEADER_MESSAGE_ID,
            HEADER_SUM, HEADER_SEQ, HEADER_BIZ_RT,
        )
        from lark_oapi.ws.model import Response as WsResp
        from lark_oapi.core.const import UTF_8

        def sync_card_handler(data: P2CardActionTrigger):
            if self._app_loop is not None and self._app_loop.is_running():
                future = asyncio.run_coroutine_threadsafe(
                    self._handle_card_action(data), self._app_loop,
                )
                try:
                    return future.result(timeout=5)
                except Exception as exc:
                    logger.error("card action handler error: %s", exc, exc_info=True)
            return {}

        handler_builder = (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_card_action_trigger(sync_card_handler)
        )

        try:
            from lark_oapi.api.im.v1 import P2ImMessageReceiveV1

            def sync_message_handler(data: P2ImMessageReceiveV1):
                if self._app_loop is not None and self._app_loop.is_running():
                    asyncio.run_coroutine_threadsafe(
                        self._handle_message(data), self._app_loop,
                    )

            handler_builder = handler_builder.register_p2_im_message_receive_v1(sync_message_handler)
            logger.info("registered p2_im_message_receive_v1 handler")
        except (ImportError, AttributeError) as exc:
            logger.warning("p2_im_message_receive_v1 not available: %s", exc)

        event_handler = handler_builder.build()

        domain = lark.LARK_DOMAIN if self._domain == "lark" else lark.FEISHU_DOMAIN
        client = lark.ws.Client(
            self._app_id,
            self._app_secret,
            event_handler=event_handler,
            log_level=lark.LogLevel.DEBUG,
            domain=domain,
        )

        def _hdr(headers, key: str) -> str:
            for h in headers:
                if h.key == key:
                    return h.value
            return ""

        async def _handle_data_frame(frame) -> None:
            hs = frame.headers
            type_ = _hdr(hs, HEADER_TYPE)
            msg_type = MessageType(type_)

            if msg_type not in (MessageType.EVENT, MessageType.CARD):
                return

            msg_id = _hdr(hs, HEADER_MESSAGE_ID)
            pl = frame.payload
            sum_ = _hdr(hs, HEADER_SUM)
            seq = _hdr(hs, HEADER_SEQ)
            if sum_ and int(sum_) > 1:
                pl = client._combine(msg_id, int(sum_), int(seq), pl)
                if pl is None:
                    return

            try:
                payload_str = pl.decode(UTF_8)
                logger.info("ws frame type=%s msg_id=%s payload=%s", msg_type.value, msg_id, payload_str[:500])
            except Exception:
                pass

            resp = WsResp(code=http.HTTPStatus.OK)
            try:
                start_ms = int(round(time.time() * 1000))
                result = client._event_handler.do_without_validation(pl)
                elapsed = int(round(time.time() * 1000)) - start_ms
                header = hs.add()
                header.key = HEADER_BIZ_RT
                header.value = str(elapsed)
                if result is not None:
                    marshaled = lark.JSON.marshal(result)
                    resp.data = base64.b64encode(marshaled.encode(UTF_8))
            except Exception as exc:
                from lark_oapi.core.exception import EventException
                if isinstance(exc, EventException) and "processor not found" in str(exc):
                    logger.debug("no handler for type=%s msg_id=%s", msg_type.value, msg_id)
                else:
                    logger.error("handler error type=%s err=%s", msg_type.value, exc, exc_info=True)
                    resp = WsResp(code=http.HTTPStatus.INTERNAL_SERVER_ERROR)

            frame.payload = lark.JSON.marshal(resp).encode(UTF_8)
            await client._write_message(frame.SerializeToString())

        client._handle_data_frame = _handle_data_frame
        return client

    # ── Lifecycle ────────────────────────────────────────────────

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        loop = asyncio.get_running_loop()
        self._app_loop = loop

        def _run_ws():
            import lark_oapi.ws.client as _ws_mod
            ws_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(ws_loop)
            _ws_mod.loop = ws_loop
            try:
                client = self._build_ws_client(loop)
                logger.info("WS connection started app=%s", self._app_id)
                client.start()
            except Exception as exc:
                logger.error("WS thread failed app=%s err=%s", self._app_id, exc, exc_info=True)

        self._ws_thread = threading.Thread(target=_run_ws, daemon=True)
        self._ws_thread.start()
        logger.info("started WS connection app=%s", self._app_id)

    async def stop(self) -> None:
        self._started = False
        logger.info("stopped WS connection app=%s", self._app_id)

"""Lark/Feishu HITL channel — long connection (WebSocket) mode via lark-oapi SDK."""
from __future__ import annotations

import asyncio
import base64
import http
import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from everstaff.channels.manager import ChannelManager
    from everstaff.protocols import HitlRequest, HitlResolution

logger = logging.getLogger(__name__)

_DOMAIN_TO_API_BASE = {
    "feishu": "https://open.feishu.cn/open-apis",
    "lark": "https://open.larksuite.com/open-apis",
}


class LarkWsChannel:
    """
    HITL channel for Lark/Feishu using long connection (WebSocket) mode.

    Outbound: POST interactive cards to a Lark chat (same HTTP API as webhook mode).
    Inbound:  lark-oapi WSClient receives card_action events over WebSocket.

    The lark-oapi SDK (as of v1.5.3) silently drops CARD frames in its
    ``_handle_data_frame`` method.  We replace that method entirely after
    constructing the client so both EVENT and CARD frames are processed.
    """

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        chat_id: str = "",
        bot_name: str = "Agent",
        file_store=None,
        channel_manager: "ChannelManager | None" = None,
        domain: str = "feishu",
    ) -> None:
        self._app_id = app_id
        self._app_secret = app_secret
        self._chat_id = chat_id
        self._bot_name = bot_name
        self._file_store = file_store
        self._channel_manager = channel_manager
        self._domain = domain
        self._api_base = _DOMAIN_TO_API_BASE.get(domain, _DOMAIN_TO_API_BASE["feishu"])
        self._config = None          # set externally by factories.py
        self._hitl_message_ids: dict[str, str] = {}
        self._hitl_requests: dict[str, "HitlRequest"] = {}
        self._started: bool = False
        self._ws_thread: threading.Thread | None = None
        self._app_loop: asyncio.AbstractEventLoop | None = None

    # ── HTTP helpers ─────────────────────────────────────────────

    async def _get_access_token(self) -> str:
        import aiohttp

        url = f"{self._api_base}/auth/v3/tenant_access_token/internal"
        async with aiohttp.ClientSession() as s:
            async with s.post(url, json={"app_id": self._app_id, "app_secret": self._app_secret}) as r:
                return (await r.json())["tenant_access_token"]

    async def _send_card(self, token: str, card: dict) -> str:
        import aiohttp

        url = f"{self._api_base}/im/v1/messages?receive_id_type=chat_id"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        body = {"receive_id": self._chat_id, "msg_type": "interactive", "content": json.dumps(card)}
        async with aiohttp.ClientSession() as s:
            async with s.post(url, headers=headers, json=body) as r:
                data = await r.json()
                mid = data.get("data", {}).get("message_id", "")
                if not mid:
                    logger.error("LarkWsChannel: send failed code=%s msg=%s", data.get("code"), data.get("msg"))
                return mid

    async def _update_card(self, token: str, message_id: str, card: dict) -> None:
        import aiohttp

        url = f"{self._api_base}/im/v1/messages/{message_id}"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        async with aiohttp.ClientSession() as s:
            async with s.patch(url, headers=headers, json={"msg_type": "interactive", "content": json.dumps(card)}) as r:
                if r.status >= 400:
                    logger.warning("LarkWsChannel: update card %s failed HTTP %s", message_id, r.status)

    # ── Card builders ────────────────────────────────────────────

    def _build_card(self, request: "HitlRequest", hitl_id: str) -> dict:
        elements: list[dict] = [
            {"tag": "div", "text": {"tag": "plain_text", "content": request.prompt}},
        ]
        if request.context:
            elements.append({"tag": "div", "text": {"tag": "plain_text", "content": f"Context: {request.context}"}})
        if request.timeout_seconds > 0:
            h, m = divmod(request.timeout_seconds, 3600)
            elements.append({"tag": "div", "text": {"tag": "plain_text", "content": f"Expires in: {h}h {m // 60}m"}})

        actions: list[dict] = []
        if request.type == "approve_reject":
            actions = [
                {"tag": "button", "text": {"tag": "plain_text", "content": "Approve"}, "type": "primary", "value": {"hitl_id": hitl_id, "decision": "approved"}},
                {"tag": "button", "text": {"tag": "plain_text", "content": "Reject"}, "type": "danger", "value": {"hitl_id": hitl_id, "decision": "rejected"}},
            ]
        elif request.type == "choose" and request.options:
            actions = [
                {"tag": "button", "text": {"tag": "plain_text", "content": opt.strip()}, "type": "default", "value": {"hitl_id": hitl_id, "decision": opt.strip()}}
                for opt in request.options
            ]
        elif request.type == "provide_input":
            elements.append({
                "tag": "form", "name": "form_1",
                "elements": [
                    {"tag": "input", "name": "user_input", "placeholder": {"tag": "plain_text", "content": "Type your response..."}},
                    {"tag": "button", "text": {"tag": "plain_text", "content": "Submit"}, "type": "primary", "action_type": "form_submit", "name": "submit", "value": {"hitl_id": hitl_id, "decision": "__input__"}},
                ],
            })

        if actions:
            elements.append({"tag": "action", "actions": actions})

        return {
            "config": {"wide_screen_mode": True},
            "header": {"title": {"tag": "plain_text", "content": f"[{self._bot_name}] Human Input Required"}, "template": "orange"},
            "elements": elements,
        }

    def _build_notify_card(self, request: "HitlRequest") -> dict:
        elements: list[dict] = [
            {"tag": "div", "text": {"tag": "plain_text", "content": request.prompt}},
        ]
        if request.context:
            elements.append({"tag": "div", "text": {"tag": "plain_text", "content": f"Context: {request.context}"}})
        return {
            "config": {"wide_screen_mode": True},
            "header": {"title": {"tag": "plain_text", "content": f"[{self._bot_name}] Notice"}, "template": "blue"},
            "elements": elements,
        }

    # ── HitlChannel protocol ────────────────────────────────────

    async def send_request(self, session_id: str, request: "HitlRequest") -> None:
        logger.info("LarkWsChannel.send_request: session=%s hitl_id=%s type=%s", session_id, request.hitl_id, request.type)
        if request.type == "notify":
            try:
                token = await self._get_access_token()
                await self._send_card(token, self._build_notify_card(request))
            except Exception as exc:
                logger.error("LarkWsChannel.send_request notify failed %s: %s", request.hitl_id, exc)
            return

        self._hitl_requests[request.hitl_id] = request
        try:
            token = await self._get_access_token()
            mid = await self._send_card(token, self._build_card(request, request.hitl_id))
            if mid:
                if self._file_store is not None:
                    await self._file_store.write(
                        f"hitl-lark-ws/{request.hitl_id}.json",
                        json.dumps({"hitl_id": request.hitl_id, "message_id": mid}).encode(),
                    )
                else:
                    self._hitl_message_ids[request.hitl_id] = mid
                logger.info("LarkWsChannel: sent card %s mid=%s", request.hitl_id, mid)
            else:
                logger.warning("LarkWsChannel: no message_id for %s", request.hitl_id)
        except Exception as exc:
            logger.error("LarkWsChannel.send_request failed %s: %s", request.hitl_id, exc)

    async def on_resolved(self, hitl_id: str, resolution: "HitlResolution") -> None:
        if self._file_store is not None:
            try:
                raw = await self._file_store.read(f"hitl-lark-ws/{hitl_id}.json")
                message_id = json.loads(raw.decode()).get("message_id")
            except Exception:
                message_id = None
        else:
            message_id = self._hitl_message_ids.get(hitl_id)

        if not message_id:
            return

        try:
            token = await self._get_access_token()
            card = {
                "config": {"wide_screen_mode": True},
                "header": {"title": {"tag": "plain_text", "content": f"[{self._bot_name}] Resolved"}, "template": "green"},
                "elements": [{"tag": "div", "text": {"tag": "plain_text", "content": (
                    f"Decision: {resolution.decision}\n"
                    f"Resolved by: {resolution.resolved_by}\n"
                    f"At: {resolution.resolved_at.strftime('%Y-%m-%d %H:%M UTC')}"
                )}}],
            }
            await self._update_card(token, message_id, card)
        except Exception as exc:
            logger.error("LarkWsChannel.on_resolved failed %s: %s", hitl_id, exc)
        finally:
            if self._file_store is not None:
                try:
                    await self._file_store.delete(f"hitl-lark-ws/{hitl_id}.json")
                except Exception:
                    pass
            self._hitl_message_ids.pop(hitl_id, None)
            self._hitl_requests.pop(hitl_id, None)

    # ── Card action handler ──────────────────────────────────────

    async def _handle_card_action(self, data: Any) -> None:
        """Parse a card button click and call channel_manager.resolve()."""
        logger.info("LarkWsChannel: card_action event received")
        try:
            event = getattr(data, "event", data)
            action = getattr(event, "action", None)
            if action is None:
                logger.warning("LarkWsChannel: no action field, skipping")
                return

            raw_value = getattr(action, "value", None)
            if isinstance(raw_value, str):
                try:
                    value = json.loads(raw_value)
                except (json.JSONDecodeError, TypeError):
                    value = {}
            else:
                value = raw_value or {}

            hitl_id = value.get("hitl_id")
            decision = value.get("decision")
            if not hitl_id or not decision:
                return

            if decision == "__input__":
                raw_form = getattr(action, "form_value", {}) or {}
                if isinstance(raw_form, str):
                    try:
                        raw_form = json.loads(raw_form)
                    except (json.JSONDecodeError, TypeError):
                        raw_form = {}
                decision = raw_form.get("user_input", "")

            operator = getattr(event, "operator", None)
            resolved_by = getattr(operator, "open_id", "lark_user") if operator else "lark_user"
            resolved_by = resolved_by or "lark_user"

            from everstaff.protocols import HitlResolution
            resolution = HitlResolution(
                decision=decision,
                resolved_at=datetime.now(timezone.utc),
                resolved_by=resolved_by,
            )

            if self._channel_manager is not None:
                await self._channel_manager.resolve(hitl_id, resolution)
                logger.info("LarkWsChannel: resolved %s decision=%s", hitl_id, decision)
        except Exception as exc:
            logger.error("LarkWsChannel._handle_card_action failed: %s", exc, exc_info=True)

    # ── WS client setup ─────────────────────────────────────────

    def _build_ws_client(self, loop: asyncio.AbstractEventLoop):
        """Build lark-oapi WSClient with replaced frame handler."""
        import lark_oapi as lark
        from lark_oapi.event.callback.model.p2_card_action_trigger import (
            P2CardActionTrigger,
            P2CardActionTriggerResponse,
        )
        from lark_oapi.ws.enum import MessageType
        from lark_oapi.ws.const import (
            HEADER_TYPE, HEADER_MESSAGE_ID, HEADER_TRACE_ID,
            HEADER_SUM, HEADER_SEQ, HEADER_BIZ_RT,
        )
        from lark_oapi.ws.model import Response as WsResp
        from lark_oapi.core.const import UTF_8

        def sync_card_handler(data: P2CardActionTrigger) -> P2CardActionTriggerResponse:
            """Dispatch card action to the app's event loop."""
            if self._app_loop is not None and self._app_loop.is_running():
                asyncio.run_coroutine_threadsafe(self._handle_card_action(data), self._app_loop)
            else:
                logger.warning("LarkWsChannel: app loop unavailable, card action dropped")
            return P2CardActionTriggerResponse({"toast": {"type": "info", "content": "Processing..."}})

        event_handler = (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_card_action_trigger(sync_card_handler)
            .build()
        )

        domain = lark.LARK_DOMAIN if self._domain == "lark" else lark.FEISHU_DOMAIN
        client = lark.ws.Client(
            self._app_id,
            self._app_secret,
            event_handler=event_handler,
            log_level=lark.LogLevel.INFO,
            domain=domain,
        )

        # ── Replace _handle_data_frame to support both EVENT and CARD ──
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
            logger.info("LarkWsChannel: %s frame msg_id=%s", msg_type.value, msg_id)

            pl = frame.payload
            sum_ = _hdr(hs, HEADER_SUM)
            seq = _hdr(hs, HEADER_SEQ)
            if sum_ and int(sum_) > 1:
                pl = client._combine(msg_id, int(sum_), int(seq), pl)
                if pl is None:
                    return

            resp = WsResp(code=http.HTTPStatus.OK)
            try:
                start_ms = int(round(time.time() * 1000))
                result = client._event_handler.do_without_validation(pl)
                elapsed = int(round(time.time() * 1000)) - start_ms
                header = hs.add()
                header.key = HEADER_BIZ_RT
                header.value = str(elapsed)
                if result is not None:
                    resp.data = base64.b64encode(lark.JSON.marshal(result).encode(UTF_8))
                logger.info("LarkWsChannel: %s handled msg_id=%s rt=%dms", msg_type.value, msg_id, elapsed)
            except Exception as exc:
                logger.error("LarkWsChannel: %s handler error msg_id=%s: %s", msg_type.value, msg_id, exc, exc_info=True)
                resp = WsResp(code=http.HTTPStatus.INTERNAL_SERVER_ERROR)

            frame.payload = lark.JSON.marshal(resp).encode(UTF_8)
            await client._write_message(frame.SerializeToString())

        client._handle_data_frame = _handle_data_frame
        logger.info("LarkWsChannel: replaced _handle_data_frame for EVENT+CARD")
        return client

    # ── Lifecycle ────────────────────────────────────────────────

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        loop = asyncio.get_running_loop()
        self._app_loop = loop

        def _run_ws():
            try:
                client = self._build_ws_client(loop)
                client.start()
            except Exception as exc:
                logger.error("LarkWsChannel WS thread failed: %s", exc)

        self._ws_thread = threading.Thread(target=_run_ws, daemon=True)
        self._ws_thread.start()
        logger.info("LarkWsChannel started — WS long connection")

    async def stop(self) -> None:
        self._started = False
        logger.info("LarkWsChannel stopped")

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
    Inbound:  lark-oapi WSClient receives card_action events over WebSocket
              via ``register_p2_card_action_trigger``.

    The installed lark-oapi SDK silently drops CARD frames in its
    ``_handle_data_frame`` (``elif MessageType.CARD: return``).
    We patch that method so CARD frames are routed through the same
    ``EventDispatcherHandler`` as EVENT frames.

    Note: ``sync_card_handler`` returns a **plain dict** instead of
    ``P2CardActionTriggerResponse`` because the SDK's ``CallBackCard``
    model only has ``{type, data}`` fields (for template cards) and
    silently drops raw card JSON (``{config, header, elements}``).
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
        logger.info("[LARK-OUT] POST %s\n  body=%s", url, json.dumps(body, ensure_ascii=False))
        async with aiohttp.ClientSession() as s:
            async with s.post(url, headers=headers, json=body) as r:
                data = await r.json()
                logger.info("[LARK-OUT] POST response status=%s\n  resp=%s", r.status, json.dumps(data, ensure_ascii=False))
                mid = data.get("data", {}).get("message_id", "")
                if not mid:
                    logger.error("[LARK-OUT] send failed code=%s msg=%s", data.get("code"), data.get("msg"))
                return mid

    async def _update_card(self, token: str, message_id: str, card: dict) -> None:
        import aiohttp

        url = f"{self._api_base}/im/v1/messages/{message_id}"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        body = {"msg_type": "interactive", "content": json.dumps(card)}
        logger.info("[LARK-OUT] PATCH %s\n  body=%s", url, json.dumps(body, ensure_ascii=False))
        async with aiohttp.ClientSession() as s:
            async with s.patch(url, headers=headers, json=body) as r:
                resp_data = await r.json()
                logger.info("[LARK-OUT] PATCH response status=%s\n  resp=%s", r.status, json.dumps(resp_data, ensure_ascii=False))

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
            "config": {"wide_screen_mode": True, "update_multi": True},
            "header": {"title": {"tag": "plain_text", "content": f"[{self._bot_name}] Human Input Required"}, "template": "orange"},
            "elements": elements,
        }

    def _build_resolved_card(
        self,
        decision: str,
        resolved_by: str,
        request: "HitlRequest | None" = None,
    ) -> dict:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        elements: list[dict] = []
        if request:
            elements.append({"tag": "div", "text": {"tag": "plain_text", "content": request.prompt}})
            if request.context:
                elements.append({"tag": "div", "text": {"tag": "plain_text", "content": f"Context: {request.context}"}})
        elements.append({"tag": "hr"})
        elements.append({"tag": "div", "text": {"tag": "plain_text", "content": (
            f"Decision: {decision}\n"
            f"Resolved by: {resolved_by}\n"
            f"Resolved At: {now}"
        )}})
        return {
            "config": {"wide_screen_mode": True},
            "header": {"title": {"tag": "plain_text", "content": f"[{self._bot_name}] Resolved"}, "template": "green"},
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
        logger.info("LarkWsChannel.on_resolved: hitl_id=%s decision=%s", hitl_id, resolution.decision)

        # Look up the message_id for this HITL card
        message_id = None
        if self._file_store is not None:
            try:
                raw = await self._file_store.read(f"hitl-lark-ws/{hitl_id}.json")
                message_id = json.loads(raw.decode()).get("message_id")
                logger.info("LarkWsChannel.on_resolved: found mid=%s from file_store", message_id)
            except Exception as exc:
                logger.warning("LarkWsChannel.on_resolved: file_store read failed for %s: %s", hitl_id, exc)
        else:
            message_id = self._hitl_message_ids.get(hitl_id)
            logger.info("LarkWsChannel.on_resolved: found mid=%s from memory", message_id)

        if not message_id:
            logger.warning("LarkWsChannel.on_resolved: no message_id for %s, cannot update card", hitl_id)
            return

        try:
            token = await self._get_access_token()
            card = self._build_resolved_card(resolution.decision, resolution.resolved_by, self._hitl_requests.get(hitl_id))
            await self._update_card(token, message_id, card)
        except Exception as exc:
            logger.error("LarkWsChannel.on_resolved: update card failed %s: %s", hitl_id, exc)
        finally:
            if self._file_store is not None:
                try:
                    await self._file_store.delete(f"hitl-lark-ws/{hitl_id}.json")
                except Exception:
                    pass
            self._hitl_message_ids.pop(hitl_id, None)
            self._hitl_requests.pop(hitl_id, None)

    # ── Card action handler ──────────────────────────────────────

    @staticmethod
    def _parse_card_action(data: Any) -> tuple[str, str, str]:
        """Extract (hitl_id, decision, resolved_by) from a card action event.

        Returns ("", "", "") if the payload cannot be parsed.
        """
        event = getattr(data, "event", data)
        action = getattr(event, "action", None)
        if action is None:
            logger.warning("[LARK-CB] _parse: no action field in event")
            return "", "", ""

        # Log raw fields for debugging
        raw_value = getattr(action, "value", None)
        raw_form = getattr(action, "form_value", None)
        logger.info("[LARK-CB] _parse: action.value=%s action.form_value=%s", raw_value, raw_form)

        if isinstance(raw_value, str):
            try:
                value = json.loads(raw_value)
            except (json.JSONDecodeError, TypeError):
                value = {}
        elif isinstance(raw_value, dict):
            value = raw_value
        else:
            value = {}

        hitl_id = value.get("hitl_id", "")
        decision = value.get("decision", "")
        if not hitl_id or not decision:
            logger.warning("[LARK-CB] _parse: missing hitl_id=%s or decision=%s in value=%s", hitl_id, decision, value)
            return "", "", ""

        if decision == "__input__":
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
            logger.info("[LARK-CB] _parse: form input resolved decision=%r", decision)

        operator = getattr(event, "operator", None)
        resolved_by = getattr(operator, "open_id", "lark_user") if operator else "lark_user"
        resolved_by = resolved_by or "lark_user"
        logger.info("[LARK-CB] _parse: hitl_id=%s decision=%r resolved_by=%s", hitl_id, decision, resolved_by)
        return hitl_id, decision, resolved_by

    async def _handle_card_action(self, hitl_id: str, decision: str, resolved_by: str) -> None:
        """Resolve HITL via channel_manager (broadcasts + persists)."""
        logger.info("LarkWsChannel._handle_card_action: hitl_id=%s decision=%r by=%s", hitl_id, decision, resolved_by)
        try:
            from everstaff.protocols import HitlResolution
            resolution = HitlResolution(
                decision=decision,
                resolved_at=datetime.now(timezone.utc),
                resolved_by=resolved_by,
            )
            if self._channel_manager is not None:
                result = await self._channel_manager.resolve(hitl_id, resolution)
                logger.info("LarkWsChannel._handle_card_action: channel_manager.resolve returned %s", result)
            else:
                logger.warning("LarkWsChannel._handle_card_action: no channel_manager set")
        except Exception as exc:
            logger.error("LarkWsChannel._handle_card_action failed: %s", exc, exc_info=True)

    # ── WS client setup ─────────────────────────────────────────

    def _build_ws_client(self, loop: asyncio.AbstractEventLoop):
        """Build lark-oapi WSClient with card action callback registered.

        The SDK's ``_handle_data_frame`` silently drops CARD frames::

            elif message_type == MessageType.CARD:
                return          # ← does nothing

        We patch it so both EVENT and CARD frames go through
        ``_event_handler.do_without_validation``, which already routes
        CARD payloads to ``register_p2_card_action_trigger``.
        """
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

        def sync_card_handler(data: P2CardActionTrigger):
            """Parse card action and dispatch resolution to the app event loop.

            Card update is handled uniformly by on_resolved() via broadcast.
            """
            logger.info("[LARK-CB] sync_card_handler ENTERED")
            hitl_id, decision, resolved_by = self._parse_card_action(data)
            if not hitl_id:
                logger.warning("[LARK-CB] parse failed, returning empty response")
                return P2CardActionTriggerResponse({})

            # Dispatch backend processing (persist + resume) to app event loop
            if self._app_loop is not None and self._app_loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    self._handle_card_action(hitl_id, decision, resolved_by),
                    self._app_loop,
                )
                logger.info("[LARK-CB] dispatched _handle_card_action to app loop")
            else:
                logger.error("[LARK-CB] app loop unavailable, action dropped!")

            return P2CardActionTriggerResponse({})

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
            log_level=lark.LogLevel.DEBUG,
            domain=domain,
        )

        # ── Patch _handle_data_frame: route CARD frames like EVENT ──

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
                logger.debug("LarkWsChannel: ignoring frame type=%s", type_)
                return

            msg_id = _hdr(hs, HEADER_MESSAGE_ID)
            trace_id = _hdr(hs, HEADER_TRACE_ID)

            pl = frame.payload
            sum_ = _hdr(hs, HEADER_SUM)
            seq = _hdr(hs, HEADER_SEQ)
            if sum_ and int(sum_) > 1:
                pl = client._combine(msg_id, int(sum_), int(seq), pl)
                if pl is None:
                    return

            # ── Log incoming event/callback ──
            try:
                payload_str = pl.decode(UTF_8)
                logger.info("[LARK-IN] %s msg_id=%s trace_id=%s\n  payload=%s", msg_type.value, msg_id, trace_id, payload_str)
            except Exception:
                logger.info("[LARK-IN] %s msg_id=%s trace_id=%s (payload decode failed)", msg_type.value, msg_id, trace_id)

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
                    logger.info("[LARK-IN] %s response type=%s rt=%dms\n  body=%s", msg_type.value, type(result).__name__, elapsed, marshaled)
                    resp.data = base64.b64encode(marshaled.encode(UTF_8))
                else:
                    logger.info("[LARK-IN] %s handler returned None rt=%dms", msg_type.value, elapsed)
            except Exception as exc:
                logger.error("[LARK-IN] %s handler error msg_id=%s: %s", msg_type.value, msg_id, exc, exc_info=True)
                resp = WsResp(code=http.HTTPStatus.INTERNAL_SERVER_ERROR)

            frame.payload = lark.JSON.marshal(resp).encode(UTF_8)
            await client._write_message(frame.SerializeToString())

        client._handle_data_frame = _handle_data_frame
        logger.info("LarkWsChannel: patched _handle_data_frame for EVENT+CARD")
        return client

    # ── Lifecycle ────────────────────────────────────────────────

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        loop = asyncio.get_running_loop()
        self._app_loop = loop

        def _run_ws():
            # Create a dedicated event loop for the WS thread.
            # The lark-oapi SDK stores a module-level `loop` that it grabs at
            # import time via asyncio.get_event_loop().  When uvloop is the
            # running policy this returns the *already-running* main loop,
            # causing `loop.run_until_complete()` inside `client.start()` to
            # fail with "this event loop is already running".
            # Patching the module-level variable lets the SDK use our fresh loop.
            import lark_oapi.ws.client as _ws_mod

            ws_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(ws_loop)
            _ws_mod.loop = ws_loop

            try:
                client = self._build_ws_client(loop)
                logger.info("LarkWsChannel: WS client built, calling start()...")
                client.start()
            except Exception as exc:
                logger.error("LarkWsChannel WS thread failed: %s", exc, exc_info=True)

        self._ws_thread = threading.Thread(target=_run_ws, daemon=True)
        self._ws_thread.start()
        logger.info("LarkWsChannel started — WS long connection")

    async def stop(self) -> None:
        self._started = False
        logger.info("LarkWsChannel stopped")

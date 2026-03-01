"""Lark/Feishu HITL channel — long connection (WebSocket) mode via lark-oapi SDK."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from everstaff.protocols import HitlRequest, HitlResolution
    from everstaff.channels.manager import ChannelManager

logger = logging.getLogger(__name__)

_DOMAIN_TO_API_BASE = {
    "feishu": "https://open.feishu.cn/open-apis",
    "lark": "https://open.larksuite.com/open-apis",
}


class LarkWsChannel:
    """
    HITL channel for Lark/Feishu using long connection (WebSocket) mode.

    Flow:
    1. start() → lark-oapi WSClient opens outbound WS to Lark's servers
    2. send_request() → HTTP POST card to Lark chat (same as webhook mode)
    3. User clicks card button → Lark pushes card_action event over WS
    4. _handle_card_action() → channel_manager.resolve()
    5. on_resolved() → HTTP PATCH card to show resolved status
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
        self._config = None  # set by create_app after construction
        self._hitl_message_ids: dict[str, str] = {}   # hitl_id → lark message_id
        self._hitl_requests: dict[str, "HitlRequest"] = {}
        self._started: bool = False
        self._ws_thread = None  # daemon thread running lark-oapi WS client
        self._app_loop: asyncio.AbstractEventLoop | None = None  # set by start()

    # ------------------------------------------------------------------
    # HTTP helpers (identical to LarkChannel)
    # ------------------------------------------------------------------

    async def _get_access_token(self) -> str:
        """Fetch tenant_access_token from Lark API."""
        import aiohttp
        url = f"{self._api_base}/auth/v3/tenant_access_token/internal"
        payload = {"app_id": self._app_id, "app_secret": self._app_secret}
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                data = await resp.json()
                return data["tenant_access_token"]

    def _build_card(self, request: "HitlRequest", hitl_id: str) -> dict:
        """Build Lark interactive card payload for a HITL request."""
        elements: list[dict] = []

        elements.append({
            "tag": "div",
            "text": {"tag": "plain_text", "content": request.prompt},
        })

        if request.context:
            elements.append({
                "tag": "div",
                "text": {"tag": "plain_text", "content": f"Context: {request.context}"},
            })

        if request.timeout_seconds > 0:
            elements.append({
                "tag": "div",
                "text": {
                    "tag": "plain_text",
                    "content": f"Expires in: {request.timeout_seconds // 3600}h {(request.timeout_seconds % 3600) // 60}m",
                },
            })

        actions: list[dict] = []
        if request.type == "approve_reject":
            actions = [
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "Approve"},
                    "type": "primary",
                    "value": {"hitl_id": hitl_id, "decision": "approved"},
                },
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "Reject"},
                    "type": "danger",
                    "value": {"hitl_id": hitl_id, "decision": "rejected"},
                },
            ]
        elif request.type == "choose" and request.options:
            actions = [
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": opt},
                    "type": "default",
                    "value": {"hitl_id": hitl_id, "decision": opt},
                }
                for opt in request.options
            ]
        elif request.type == "provide_input":
            elements.append({
                "tag": "action",
                "actions": [{
                    "tag": "input",
                    "placeholder": {"tag": "plain_text", "content": "Type your response..."},
                    "name": "user_input",
                }],
            })
            actions = [
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "Submit"},
                    "type": "primary",
                    "value": {"hitl_id": hitl_id, "decision": "__input__"},
                }
            ]

        if actions:
            elements.append({"tag": "action", "actions": actions})

        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": f"[{self._bot_name}] Human Input Required",
                },
                "template": "orange",
            },
            "elements": elements,
        }

    def _build_notify_card(self, request: "HitlRequest") -> dict:
        """Build a display-only Lark card (no buttons) for notify type."""
        elements: list[dict] = [
            {"tag": "div", "text": {"tag": "plain_text", "content": request.prompt}}
        ]
        if request.context:
            elements.append({
                "tag": "div",
                "text": {"tag": "plain_text", "content": f"Context: {request.context}"},
            })
        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": f"[{self._bot_name}] Notice"},
                "template": "blue",
            },
            "elements": elements,
        }

    async def _send_card(self, token: str, card: dict) -> str:
        """Send card to Lark chat. Returns message_id or empty string on failure."""
        import aiohttp
        url = f"{self._api_base}/im/v1/messages?receive_id_type=chat_id"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        payload = {
            "receive_id": self._chat_id,
            "msg_type": "interactive",
            "content": json.dumps(card),
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                data = await resp.json()
                return data.get("data", {}).get("message_id", "")

    async def _update_card(self, token: str, message_id: str, card: dict) -> None:
        """Update an existing Lark card message."""
        import aiohttp
        url = f"{self._api_base}/im/v1/messages/{message_id}"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        payload = {"msg_type": "interactive", "content": json.dumps(card)}
        async with aiohttp.ClientSession() as session:
            async with session.patch(url, headers=headers, json=payload) as resp:
                if resp.status >= 400:
                    logger.warning(
                        "Failed to update Lark card %s: HTTP %s", message_id, resp.status
                    )

    # ------------------------------------------------------------------
    # HitlChannel protocol methods
    # ------------------------------------------------------------------

    async def send_request(self, session_id: str, request: "HitlRequest") -> None:
        logger.info(
            "LarkWsChannel.send_request: session=%s hitl_id=%s type=%s",
            session_id, request.hitl_id, request.type,
        )
        if request.type == "notify":
            try:
                token = await self._get_access_token()
                card = self._build_notify_card(request)
                await self._send_card(token, card)
            except Exception as exc:
                logger.error(
                    "LarkWsChannel.send_request (notify) failed for %s: %s",
                    request.hitl_id, exc,
                )
            return
        self._hitl_requests[request.hitl_id] = request
        try:
            token = await self._get_access_token()
            card = self._build_card(request, request.hitl_id)
            message_id = await self._send_card(token, card)
            if message_id:
                if self._file_store is not None:
                    await self._file_store.write(
                        f"hitl-lark-ws/{request.hitl_id}.json",
                        json.dumps({"hitl_id": request.hitl_id, "message_id": message_id}).encode(),
                    )
                else:
                    self._hitl_message_ids[request.hitl_id] = message_id
                logger.info(
                    "LarkWsChannel: sent HITL card for %s, message_id=%s",
                    request.hitl_id, message_id,
                )
            else:
                logger.warning("LarkWsChannel: _send_card returned no message_id for %s", request.hitl_id)
        except Exception as exc:
            logger.error("LarkWsChannel.send_request failed for %s: %s", request.hitl_id, exc)

    async def on_resolved(self, hitl_id: str, resolution: "HitlResolution") -> None:
        if self._file_store is not None:
            try:
                raw = await self._file_store.read(f"hitl-lark-ws/{hitl_id}.json")
                data = json.loads(raw.decode())
                message_id = data.get("message_id")
            except Exception:
                message_id = None
        else:
            message_id = self._hitl_message_ids.get(hitl_id)
        if not message_id:
            return
        try:
            token = await self._get_access_token()
            resolved_card = {
                "config": {"wide_screen_mode": True},
                "header": {
                    "title": {"tag": "plain_text", "content": f"[{self._bot_name}] Resolved"},
                    "template": "green",
                },
                "elements": [{
                    "tag": "div",
                    "text": {
                        "tag": "plain_text",
                        "content": (
                            f"Decision: {resolution.decision}\n"
                            f"Resolved by: {resolution.resolved_by}\n"
                            f"At: {resolution.resolved_at.strftime('%Y-%m-%d %H:%M UTC')}"
                        ),
                    },
                }],
            }
            await self._update_card(token, message_id, resolved_card)
        except Exception as exc:
            logger.error("LarkWsChannel.on_resolved failed for %s: %s", hitl_id, exc)
        finally:
            if self._file_store is not None:
                try:
                    await self._file_store.delete(f"hitl-lark-ws/{hitl_id}.json")
                except Exception:
                    pass
            self._hitl_message_ids.pop(hitl_id, None)
            self._hitl_requests.pop(hitl_id, None)

    # ------------------------------------------------------------------
    # Card action handler (called by lark-oapi WS event dispatcher)
    # ------------------------------------------------------------------

    async def _handle_card_action(self, data: Any) -> None:
        """Handle card button click event received over WS."""
        logger.info("LarkWsChannel: received card_action event via WS")
        try:
            # Log raw data for debugging
            try:
                import lark_oapi as _lark
                logger.info("LarkWsChannel: raw card_action data: %s", _lark.JSON.marshal(data))
            except Exception:
                logger.info("LarkWsChannel: card_action data type=%s", type(data))

            # P2CardActionTrigger nests payload under .event
            event = getattr(data, "event", data)
            action = getattr(event, "action", None)
            if action is None:
                logger.warning("LarkWsChannel: card_action has no action field, skipping")
                return

            raw_value = getattr(action, "value", None)
            # value may be a JSON string or a dict depending on SDK version
            if isinstance(raw_value, str):
                try:
                    value = json.loads(raw_value)
                except (json.JSONDecodeError, TypeError):
                    value = {}
            else:
                value = raw_value or {}
            hitl_id = value.get("hitl_id")
            decision = value.get("decision")
            logger.info("LarkWsChannel: card_action hitl_id=%s decision=%s", hitl_id, decision)

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
                logger.info("LarkWsChannel: resolved HITL %s decision=%s", hitl_id, decision)

            # Resume the paused agent session (mirrors webhook handler logic)
            if self._file_store is not None:
                await self._resume_session(hitl_id, decision, resolved_by)
        except Exception as exc:
            logger.error("LarkWsChannel._handle_card_action failed: %s", exc, exc_info=True)

    async def _resume_session(self, hitl_id: str, decision: str, resolved_by: str) -> None:
        """Find the session containing hitl_id and resume it via session.json."""
        try:
            # Scan session dirs to find which session.json contains this hitl_id
            session_id = None
            session_raw = {}
            paths = await self._file_store.list("")
            for path in paths:
                if not path.endswith("/session.json"):
                    continue
                try:
                    raw = await self._file_store.read(path)
                    data = json.loads(raw.decode())
                    for item in data.get("hitl_requests", []):
                        if item.get("hitl_id") == hitl_id and item.get("status") == "pending":
                            session_id = data.get("session_id") or path.split("/")[0]
                            session_raw = data
                            break
                    if session_id:
                        break
                except Exception:
                    continue

            if not session_id:
                return

            # Update session.json: mark hitl as resolved
            for item in session_raw.get("hitl_requests", []):
                if item.get("hitl_id") == hitl_id:
                    item["status"] = "resolved"
                    item["response"] = {
                        "decision": decision,
                        "comment": None,
                        "resolved_at": datetime.now(timezone.utc).isoformat(),
                        "resolved_by": resolved_by,
                    }
                    break

            # Only resume when ALL pending HITLs in this session are settled
            pending = [
                i for i in session_raw.get("hitl_requests", [])
                if i.get("status") == "pending"
            ]
            session_raw["status"] = "running" if not pending else session_raw.get("status", "waiting_for_human")
            await self._file_store.write(
                f"{session_id}/session.json",
                json.dumps(session_raw, ensure_ascii=False, indent=2).encode(),
            )

            if pending:
                logger.info("LarkWsChannel: %d HITL(s) still pending for session %s", len(pending), session_id)
                return

            agent_name = session_raw.get("agent_name", "")
            config = getattr(self, "_config", None)
            if config is None:
                logger.warning("LarkWsChannel: no config set, cannot resume session %s", session_id)
                return

            from everstaff.api.sessions import _resume_session_task
            coro = _resume_session_task(
                session_id, agent_name, "", config,
                channel_manager=self._channel_manager,
            )
            # Submit the long-running resume task to the app's event loop
            # (this handler runs in a short-lived thread with its own loop)
            if self._app_loop is not None and self._app_loop.is_running():
                asyncio.run_coroutine_threadsafe(coro, self._app_loop)
            else:
                # Fallback: run in current event loop
                asyncio.ensure_future(coro)
        except Exception as exc:
            logger.error("LarkWsChannel._resume_session failed for %s: %s", hitl_id, exc)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _build_ws_client(self, loop: asyncio.AbstractEventLoop):
        """Build and return the lark-oapi WSClient. Separated for testability."""
        import lark_oapi as lark
        from lark_oapi.event.callback.model.p2_card_action_trigger import (
            P2CardActionTrigger,
            P2CardActionTriggerResponse,
        )

        def sync_card_handler(data: P2CardActionTrigger) -> P2CardActionTriggerResponse:
            """Sync wrapper: runs _handle_card_action in a dedicated thread+event loop.

            We cannot rely on the app's main event loop (it may be blocked by
            CLI ``input()`` or busy serving HTTP requests).  Instead, spin up
            a short-lived event loop in a daemon thread so all async I/O
            (HTTP PATCH, file-store reads) completes immediately.
            """
            import threading

            def _run():
                _loop = asyncio.new_event_loop()
                try:
                    _loop.run_until_complete(self._handle_card_action(data))
                except Exception as exc:
                    logger.error("LarkWsChannel: _handle_card_action raised: %s", exc, exc_info=True)
                finally:
                    _loop.close()

            logger.info("LarkWsChannel: WS event dispatched — card_action_trigger received")
            threading.Thread(target=_run, daemon=True).start()
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

        # ── Monkey-patch: SDK ignores MessageType.CARD in _handle_data_frame ──
        # The lark-oapi WS client's _handle_data_frame has:
        #   elif message_type == MessageType.CARD: return
        # This silently drops card action callbacks, causing Feishu error 200340.
        # We patch it to route CARD messages through the event handler.
        try:
            from lark_oapi.ws.enum import MessageType as _MT
            from lark_oapi.ws.const import (
                HEADER_MESSAGE_ID, HEADER_TRACE_ID, HEADER_TYPE,
                HEADER_SUM, HEADER_SEQ, HEADER_BIZ_RT,
            )
            from lark_oapi.ws.model import Response as _WsResponse
            from lark_oapi.ws.pb.pbbp2_pb2 import Frame as _Frame
            import base64 as _b64
            import http as _http
            import time as _time

            _orig_handle = client._handle_data_frame

            def _get_by_key(headers, key):
                for h in headers:
                    if h.key == key:
                        return h.value
                return ""

            async def _patched_handle_data_frame(frame):
                hs = frame.headers
                type_ = _get_by_key(hs, HEADER_TYPE)
                msg_type = _MT(type_)
                if msg_type == _MT.CARD:
                    # Process CARD the same way as EVENT
                    msg_id = _get_by_key(hs, HEADER_MESSAGE_ID)
                    trace_id = _get_by_key(hs, HEADER_TRACE_ID)
                    logger.info(
                        "LarkWsChannel: [patched] handling CARD message msg_id=%s trace_id=%s",
                        msg_id, trace_id,
                    )
                    pl = frame.payload
                    # Handle multi-part messages
                    sum_ = _get_by_key(hs, HEADER_SUM)
                    seq = _get_by_key(hs, HEADER_SEQ)
                    if int(sum_ or "1") > 1:
                        pl = client._combine(msg_id, int(sum_), int(seq), pl)
                        if pl is None:
                            return

                    resp = _WsResponse(code=_http.HTTPStatus.OK)
                    try:
                        start = int(round(_time.time() * 1000))
                        result = client._event_handler.do_without_validation(pl)
                        end = int(round(_time.time() * 1000))
                        header = hs.add()
                        header.key = HEADER_BIZ_RT
                        header.value = str(end - start)
                        if result is not None:
                            resp.data = _b64.b64encode(
                                lark.JSON.marshal(result).encode("utf-8")
                            )
                    except Exception as exc:
                        logger.error(
                            "LarkWsChannel: [patched] CARD handler error msg_id=%s: %s",
                            msg_id, exc, exc_info=True,
                        )
                        resp = _WsResponse(code=_http.HTTPStatus.INTERNAL_SERVER_ERROR)

                    frame.payload = lark.JSON.marshal(resp).encode("utf-8")
                    await client._write_message(frame.SerializeToString())
                else:
                    await _orig_handle(frame)

            client._handle_data_frame = _patched_handle_data_frame
            logger.info("LarkWsChannel: patched ws.Client._handle_data_frame to handle CARD messages")
        except Exception as exc:
            logger.warning("LarkWsChannel: failed to patch ws.Client for CARD handling: %s", exc)

        return client

    async def start(self) -> None:
        """Start the WS long connection in a daemon thread.

        Uses a daemon thread so the process can exit cleanly on Ctrl+C
        without waiting for the blocking ``client.start()`` to return.
        """
        if self._started:
            return
        self._started = True
        loop = asyncio.get_running_loop()
        self._app_loop = loop

        import threading

        def _run_ws():
            try:
                client = self._build_ws_client(loop)
                client.start()
            except Exception as exc:
                logger.error("LarkWsChannel WS thread failed: %s", exc)

        self._ws_thread = threading.Thread(target=_run_ws, daemon=True)
        self._ws_thread.start()
        logger.info("LarkWsChannel started — long connection to Lark WS endpoint")

    async def stop(self) -> None:
        """Mark channel as stopped. The daemon thread exits when the process does."""
        self._started = False
        logger.info("LarkWsChannel stopped")

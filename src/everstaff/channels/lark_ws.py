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
        web_url: str = "",
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
        self._web_url = web_url.rstrip("/") if web_url else ""
        self._hitl_message_ids: dict[str, str] = {}
        self._hitl_requests: dict[str, "HitlRequest"] = {}
        self._hitl_session_ids: dict[str, str] = {}   # hitl_id -> session_id
        self._username_cache: dict[str, str] = {}     # open_id -> display name
        self._started: bool = False
        self._ws_thread: threading.Thread | None = None
        self._app_loop: asyncio.AbstractEventLoop | None = None
        self._expiration_task: asyncio.Task | None = None

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
        logger.info("POST url=%s body=%s", url, json.dumps(body, ensure_ascii=False))
        async with aiohttp.ClientSession() as s:
            async with s.post(url, headers=headers, json=body) as r:
                data = await r.json()
                logger.info("POST response status=%s resp=%s", r.status, json.dumps(data, ensure_ascii=False))
                mid = data.get("data", {}).get("message_id", "")
                if not mid:
                    logger.error("send failed code=%s msg=%s", data.get("code"), data.get("msg"))
                return mid

    async def _update_card(self, token: str, message_id: str, card: dict) -> None:
        import aiohttp

        url = f"{self._api_base}/im/v1/messages/{message_id}"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        body = {"msg_type": "interactive", "content": json.dumps(card)}
        logger.info("PATCH url=%s body=%s", url, json.dumps(body, ensure_ascii=False))
        async with aiohttp.ClientSession() as s:
            async with s.patch(url, headers=headers, json=body) as r:
                resp_data = await r.json()
                logger.info("PATCH response status=%s resp=%s", r.status, json.dumps(resp_data, ensure_ascii=False))

    async def _resolve_username(self, open_id: str) -> str:
        """Resolve Lark open_id to display name via API. Cached in memory."""
        if open_id in self._username_cache:
            return self._username_cache[open_id]
        try:
            import aiohttp
            token = await self._get_access_token()
            url = f"{self._api_base}/contact/v3/users/{open_id}?user_id_type=open_id"
            headers = {"Authorization": f"Bearer {token}"}
            async with aiohttp.ClientSession() as s:
                async with s.get(url, headers=headers) as r:
                    data = await r.json()
                    code = data.get("code", 0)
                    if code != 0:
                        logger.warning("resolve_username API error open_id=%s code=%s msg=%s", open_id, code, data.get("msg"))
                        self._username_cache[open_id] = open_id
                        return open_id
                    name = data.get("data", {}).get("user", {}).get("name", open_id)
                    logger.info("resolve_username open_id=%s -> name=%s", open_id, name)
                    self._username_cache[open_id] = name
                    return name
        except Exception as exc:
            logger.warning("resolve_username failed open_id=%s err=%s", open_id, exc)
            self._username_cache[open_id] = open_id
            return open_id

    # ── Card builders ────────────────────────────────────────────

    def _build_card(self, request: "HitlRequest", hitl_id: str, session_id: str = "") -> dict:
        elements: list[dict] = []

        # ── Prompt (bold, markdown) ──
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": f"**{request.prompt}**"}})

        # ── Tool details (tool_permission type) ──
        if request.type == "tool_permission" and request.tool_name:
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": f"Tool: `{request.tool_name}`"}})
            if request.tool_args:
                args_text = json.dumps(request.tool_args, ensure_ascii=False, indent=2)
                if len(args_text) > 1000:
                    args_text = args_text[:1000] + "\n..."
                elements.append({
                    "tag": "collapsible_panel",
                    "expanded": False,
                    "header": {"title": {"tag": "plain_text", "content": "Parameters"}},
                    "border": {"color": "grey"},
                    "vertical_spacing": "8px",
                    "elements": [
                        {"tag": "div", "text": {"tag": "plain_text", "content": args_text}},
                    ],
                })

        # ── Context (collapsible if long, inline if short) ──
        if request.context:
            if len(request.context) > 100:
                elements.append({
                    "tag": "collapsible_panel",
                    "expanded": False,
                    "header": {"title": {"tag": "plain_text", "content": "Context"}},
                    "border": {"color": "grey"},
                    "vertical_spacing": "8px",
                    "elements": [
                        {"tag": "div", "text": {"tag": "lark_md", "content": request.context}},
                    ],
                })
            else:
                elements.append({"tag": "div", "text": {"tag": "lark_md", "content": request.context}})

        # ── Action buttons ──
        actions: list[dict] = []
        if request.type == "approve_reject":
            actions = [
                {"tag": "button", "text": {"tag": "plain_text", "content": "Approve"}, "type": "primary", "value": {"hitl_id": hitl_id, "decision": "approved"}},
                {"tag": "button", "text": {"tag": "plain_text", "content": "Reject"}, "type": "danger", "value": {"hitl_id": hitl_id, "decision": "rejected"}},
            ]
        elif request.type == "tool_permission":
            if request.tool_permission_options:
                _TYPE_MAP = {"reject": "danger", "approve_once": "default"}
                for opt in request.tool_permission_options:
                    btn_type = _TYPE_MAP.get(opt.get("id", ""), "primary")
                    value: dict = {"hitl_id": hitl_id, "decision": opt["id"]}
                    if opt.get("scope"):
                        value["grant_scope"] = opt["scope"]
                    if opt.get("pattern"):
                        value["permission_pattern"] = opt["pattern"]
                    actions.append({"tag": "button", "text": {"tag": "plain_text", "content": opt["label"]}, "type": btn_type, "value": value})
            else:
                actions = [
                    {"tag": "button", "text": {"tag": "plain_text", "content": "Reject"}, "type": "danger", "value": {"hitl_id": hitl_id, "decision": "rejected", "grant_scope": "once"}},
                    {"tag": "button", "text": {"tag": "plain_text", "content": "Approve Once"}, "type": "default", "value": {"hitl_id": hitl_id, "decision": "approved", "grant_scope": "once"}},
                    {"tag": "button", "text": {"tag": "plain_text", "content": "Approve Session"}, "type": "primary", "value": {"hitl_id": hitl_id, "decision": "approved", "grant_scope": "session"}},
                    {"tag": "button", "text": {"tag": "plain_text", "content": "Approve Always"}, "type": "primary", "value": {"hitl_id": hitl_id, "decision": "approved", "grant_scope": "permanent"}},
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

        # ── Footer note: session link + expiration ──
        note_parts: list[str] = []
        if session_id:
            short_id = session_id[:8].upper()
            if self._web_url:
                note_parts.append(f"[Session {short_id}]({self._web_url}/sessions/{session_id})")
            else:
                note_parts.append(f"Session: {short_id}")
        if request.timeout_seconds > 0:
            h, remainder = divmod(request.timeout_seconds, 3600)
            m = remainder // 60
            if h > 0:
                note_parts.append(f"Expires in {h}h {m}m")
            else:
                note_parts.append(f"Expires in {m}m")
        if note_parts:
            elements.append({"tag": "hr"})
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": " | ".join(note_parts)}})

        return {
            "config": {"wide_screen_mode": True, "update_multi": True},
            "header": {"title": {"tag": "plain_text", "content": f"[{self._bot_name}] Needs Approval"}, "template": "orange"},
            "elements": elements,
        }

    def _build_resolved_card(
        self,
        decision: str,
        resolved_by: str,
        request: "HitlRequest | None" = None,
        session_id: str = "",
    ) -> dict:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        elements: list[dict] = []

        # ── Original content preserved ──
        if request:
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": f"**{request.prompt}**"}})
            if request.type == "tool_permission" and request.tool_name:
                elements.append({"tag": "div", "text": {"tag": "lark_md", "content": f"Tool: `{request.tool_name}`"}})
                if request.tool_args:
                    args_text = json.dumps(request.tool_args, ensure_ascii=False, indent=2)
                    if len(args_text) > 1000:
                        args_text = args_text[:1000] + "\n..."
                    elements.append({
                        "tag": "collapsible_panel",
                        "expanded": False,
                        "header": {"title": {"tag": "plain_text", "content": "Parameters"}},
                        "border": {"color": "grey"},
                        "vertical_spacing": "8px",
                        "elements": [
                            {"tag": "div", "text": {"tag": "plain_text", "content": args_text}},
                        ],
                    })
            if request.context:
                if len(request.context) > 100:
                    elements.append({
                        "tag": "collapsible_panel",
                        "expanded": False,
                        "header": {"title": {"tag": "plain_text", "content": "Context"}},
                        "border": {"color": "grey"},
                        "vertical_spacing": "8px",
                        "elements": [
                            {"tag": "div", "text": {"tag": "lark_md", "content": request.context}},
                        ],
                    })
                else:
                    elements.append({"tag": "div", "text": {"tag": "lark_md", "content": request.context}})

        # ── Resolution details ──
        elements.append({"tag": "hr"})
        _DECISION_LABELS = {
            "approved": "Approved", "rejected": "Rejected",
            "approve_once": "Approved (once)", "approve_session": "Approved (session)",
            "approve_session_narrow": "Approved (session, narrow)",
            "approve_permanent": "Approved (always)",
            "approve_permanent_narrow": "Approved (always, narrow)",
        }
        decision_label = _DECISION_LABELS.get(decision, decision)
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": (
            f"**Decision:** {decision_label}\n"
            f"**Operator:** {resolved_by}\n"
            f"**Time:** {now}"
        )}})

        # ── Footer note ──
        note_parts: list[str] = []
        if session_id:
            short_id = session_id[:8].upper()
            if self._web_url:
                note_parts.append(f"[Session {short_id}]({self._web_url}/sessions/{session_id})")
            else:
                note_parts.append(f"Session: {short_id}")
        if note_parts:
            elements.append({"tag": "hr"})
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": " | ".join(note_parts)}})

        is_rejected = decision in ("rejected", "reject")
        header_template = "red" if is_rejected else "green"
        header_label = "Rejected" if is_rejected else "Resolved"
        return {
            "config": {"wide_screen_mode": True, "update_multi": True},
            "header": {"title": {"tag": "plain_text", "content": f"[{self._bot_name}] {header_label}"}, "template": header_template},
            "elements": elements,
        }

    def _build_expired_card(
        self,
        request: "HitlRequest | None" = None,
        session_id: str = "",
    ) -> dict:
        elements: list[dict] = []

        if request:
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": f"**{request.prompt}**"}})
            if request.type == "tool_permission" and request.tool_name:
                elements.append({"tag": "div", "text": {"tag": "lark_md", "content": f"Tool: `{request.tool_name}`"}})
                if request.tool_args:
                    args_text = json.dumps(request.tool_args, ensure_ascii=False, indent=2)
                    if len(args_text) > 1000:
                        args_text = args_text[:1000] + "\n..."
                    elements.append({
                        "tag": "collapsible_panel",
                        "expanded": False,
                        "header": {"title": {"tag": "plain_text", "content": "Parameters"}},
                        "border": {"color": "grey"},
                        "vertical_spacing": "8px",
                        "elements": [
                            {"tag": "div", "text": {"tag": "plain_text", "content": args_text}},
                        ],
                    })
            if request.context:
                elements.append({
                    "tag": "collapsible_panel",
                    "expanded": False,
                    "header": {"title": {"tag": "plain_text", "content": "Context"}},
                    "border": {"color": "grey"},
                    "vertical_spacing": "8px",
                    "elements": [
                        {"tag": "div", "text": {"tag": "lark_md", "content": request.context}},
                    ],
                })

        elements.append({"tag": "hr"})
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "**This request has expired and can no longer be acted upon.**"}})

        # Footer
        note_parts: list[str] = []
        if session_id:
            short_id = session_id[:8].upper()
            if self._web_url:
                note_parts.append(f"[Session {short_id}]({self._web_url}/sessions/{session_id})")
            else:
                note_parts.append(f"Session: {short_id}")
        if note_parts:
            elements.append({"tag": "hr"})
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": " | ".join(note_parts)}})

        return {
            "config": {"wide_screen_mode": True, "update_multi": True},
            "header": {"title": {"tag": "plain_text", "content": f"[{self._bot_name}] Expired"}, "template": "grey"},
            "elements": elements,
        }

    def _build_notify_card(self, request: "HitlRequest") -> dict:
        elements: list[dict] = [
            {"tag": "div", "text": {"tag": "lark_md", "content": f"**{request.prompt}**"}},
        ]
        if request.context:
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": request.context}})
        return {
            "config": {"wide_screen_mode": True, "update_multi": True},
            "header": {"title": {"tag": "plain_text", "content": f"[{self._bot_name}] Notice"}, "template": "blue"},
            "elements": elements,
        }

    # ── HitlChannel protocol ────────────────────────────────────

    async def send_request(self, session_id: str, request: "HitlRequest") -> None:
        logger.info("send_request session=%s hitl_id=%s type=%s", session_id, request.hitl_id, request.type)
        if request.type == "notify":
            try:
                token = await self._get_access_token()
                await self._send_card(token, self._build_notify_card(request))
            except Exception as exc:
                logger.error("send_request notify failed hitl_id=%s err=%s", request.hitl_id, exc)
            return

        self._hitl_requests[request.hitl_id] = request
        self._hitl_session_ids[request.hitl_id] = session_id
        try:
            token = await self._get_access_token()
            mid = await self._send_card(token, self._build_card(request, request.hitl_id, session_id))
            if mid:
                if self._file_store is not None:
                    await self._file_store.write(
                        f"hitl-lark-ws/{request.hitl_id}.json",
                        json.dumps({"hitl_id": request.hitl_id, "message_id": mid}).encode(),
                    )
                else:
                    self._hitl_message_ids[request.hitl_id] = mid
                logger.info("sent card hitl_id=%s mid=%s", request.hitl_id, mid)
            else:
                logger.warning("no message_id for hitl_id=%s", request.hitl_id)
        except Exception as exc:
            logger.error("send_request failed hitl_id=%s err=%s", request.hitl_id, exc)

    async def on_resolved(self, hitl_id: str, resolution: "HitlResolution") -> None:
        logger.info("on_resolved hitl_id=%s decision=%s", hitl_id, resolution.decision)

        # Look up the message_id for this HITL card
        message_id = None
        if self._file_store is not None:
            try:
                raw = await self._file_store.read(f"hitl-lark-ws/{hitl_id}.json")
                message_id = json.loads(raw.decode()).get("message_id")
                logger.info("on_resolved found mid=%s source=file_store", message_id)
            except Exception as exc:
                logger.warning("on_resolved file_store read failed hitl_id=%s err=%s", hitl_id, exc)
        else:
            message_id = self._hitl_message_ids.get(hitl_id)
            logger.info("on_resolved found mid=%s source=memory", message_id)

        if not message_id:
            logger.warning("on_resolved no message_id for hitl_id=%s, cannot update card", hitl_id)
            return

        try:
            token = await self._get_access_token()
            display_name = await self._resolve_username(resolution.resolved_by)
            session_id = self._hitl_session_ids.get(hitl_id, "")
            card = self._build_resolved_card(
                resolution.decision, display_name,
                self._hitl_requests.get(hitl_id), session_id,
            )
            await self._update_card(token, message_id, card)
        except Exception as exc:
            logger.error("on_resolved update card failed hitl_id=%s err=%s", hitl_id, exc, exc_info=True)
        finally:
            if self._file_store is not None:
                try:
                    await self._file_store.delete(f"hitl-lark-ws/{hitl_id}.json")
                except Exception:
                    pass
            self._hitl_message_ids.pop(hitl_id, None)
            self._hitl_requests.pop(hitl_id, None)
            self._hitl_session_ids.pop(hitl_id, None)

    # ── Card action handler ──────────────────────────────────────

    @staticmethod
    def _parse_card_action(data: Any) -> tuple[str, str, str, str | None, str | None]:
        """Extract (hitl_id, decision, resolved_by, grant_scope, permission_pattern) from a card action event.

        Returns ("", "", "", None, None) if the payload cannot be parsed.
        """
        event = getattr(data, "event", data)
        action = getattr(event, "action", None)
        if action is None:
            logger.warning("parse action: no action field in event")
            return "", "", "", None, None

        # Log raw fields for debugging
        raw_value = getattr(action, "value", None)
        raw_form = getattr(action, "form_value", None)
        logger.info("parse action value=%s form_value=%s", raw_value, raw_form)

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
        grant_scope = value.get("grant_scope")
        permission_pattern = value.get("permission_pattern")
        if not hitl_id or not decision:
            logger.warning("parse action: missing hitl_id=%s or decision=%s value=%s", hitl_id, decision, value)
            return "", "", "", None, None

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
            logger.info("parse action form input resolved decision=%r", decision)

        operator = getattr(event, "operator", None)
        resolved_by = getattr(operator, "open_id", "lark_user") if operator else "lark_user"
        resolved_by = resolved_by or "lark_user"
        logger.info("parse action hitl_id=%s decision=%r resolved_by=%s grant_scope=%s pattern=%s", hitl_id, decision, resolved_by, grant_scope, permission_pattern)
        return hitl_id, decision, resolved_by, grant_scope, permission_pattern

    async def _handle_card_action(self, hitl_id: str, decision: str, resolved_by: str, grant_scope: str | None = None, permission_pattern: str | None = None) -> None:
        """Resolve HITL via channel_manager (broadcasts + persists)."""
        logger.info("handle_card_action hitl_id=%s decision=%r by=%s grant_scope=%s pattern=%s", hitl_id, decision, resolved_by, grant_scope, permission_pattern)
        try:
            from everstaff.protocols import HitlResolution
            resolution = HitlResolution(
                decision=decision,
                resolved_at=datetime.now(timezone.utc),
                resolved_by=resolved_by,
                grant_scope=grant_scope,
                permission_pattern=permission_pattern,
            )
            if self._channel_manager is not None:
                result = await self._channel_manager.resolve(hitl_id, resolution)
                logger.info("handle_card_action channel_manager.resolve returned result=%s", result)
            else:
                logger.warning("handle_card_action no channel_manager set")
        except Exception as exc:
            logger.error("handle_card_action failed err=%s", exc, exc_info=True)

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

            Returns a toast response for immediate user feedback.
            Card update to "Resolved" state is handled by on_resolved() via broadcast.
            """
            logger.info("sync_card_handler entered")
            hitl_id, decision, resolved_by, grant_scope, permission_pattern = self._parse_card_action(data)
            if not hitl_id:
                logger.warning("sync_card_handler parse failed, returning empty response")
                return P2CardActionTriggerResponse({})

            # Build resolved card synchronously for immediate callback response
            request = self._hitl_requests.get(hitl_id)
            session_id = self._hitl_session_ids.get(hitl_id, "")
            resolved_card = self._build_resolved_card(
                decision, resolved_by, request, session_id,
            )
            logger.info("sync_card_handler built resolved card for hitl_id=%s", hitl_id)

            # Dispatch backend processing (persist + resume) to app event loop
            if self._app_loop is not None and self._app_loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    self._handle_card_action(hitl_id, decision, resolved_by, grant_scope, permission_pattern),
                    self._app_loop,
                )
                logger.info("sync_card_handler dispatched handle_card_action to app loop")
            else:
                logger.error("sync_card_handler app loop unavailable, action dropped")

            # Return resolved card directly — Lark replaces the current card
            return resolved_card

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
                logger.debug("ignoring frame type=%s", type_)
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
                logger.info("received type=%s msg_id=%s trace_id=%s payload=%s", msg_type.value, msg_id, trace_id, payload_str)
            except Exception:
                logger.info("received type=%s msg_id=%s trace_id=%s (payload decode failed)", msg_type.value, msg_id, trace_id)

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
                    logger.info("response type=%s result_type=%s rt=%dms body=%s", msg_type.value, type(result).__name__, elapsed, marshaled)
                    resp.data = base64.b64encode(marshaled.encode(UTF_8))
                else:
                    logger.info("handler returned None type=%s rt=%dms", msg_type.value, elapsed)
            except Exception as exc:
                from lark_oapi.core.exception import EventException
                if isinstance(exc, EventException) and "processor not found" in str(exc):
                    logger.debug("no handler for event type=%s msg_id=%s (ignored)", msg_type.value, msg_id)
                else:
                    logger.error("handler error type=%s msg_id=%s err=%s", msg_type.value, msg_id, exc, exc_info=True)
                    resp = WsResp(code=http.HTTPStatus.INTERNAL_SERVER_ERROR)

            frame.payload = lark.JSON.marshal(resp).encode(UTF_8)
            await client._write_message(frame.SerializeToString())

        client._handle_data_frame = _handle_data_frame
        logger.info("patched _handle_data_frame for EVENT+CARD")
        return client

    # ── Expiration polling ──────────────────────────────────────

    async def _expiration_poll_loop(self) -> None:
        """Background task: check for expired HITL requests every 60s and update cards."""
        while True:
            await asyncio.sleep(60)
            try:
                now = datetime.now(timezone.utc)
                expired_ids: list[str] = []
                for hitl_id, request in list(self._hitl_requests.items()):
                    if request.timeout_seconds <= 0:
                        continue
                    age = (now - request.created_at).total_seconds()
                    if age > request.timeout_seconds:
                        expired_ids.append(hitl_id)

                for hitl_id in expired_ids:
                    request = self._hitl_requests.get(hitl_id)
                    session_id = self._hitl_session_ids.get(hitl_id, "")
                    message_id = None
                    if self._file_store is not None:
                        try:
                            raw = await self._file_store.read(f"hitl-lark-ws/{hitl_id}.json")
                            message_id = json.loads(raw.decode()).get("message_id")
                        except Exception:
                            pass
                    else:
                        message_id = self._hitl_message_ids.get(hitl_id)

                    if message_id:
                        try:
                            token = await self._get_access_token()
                            card = self._build_expired_card(request, session_id)
                            await self._update_card(token, message_id, card)
                            logger.info("expired card updated hitl_id=%s", hitl_id)
                        except Exception as exc:
                            logger.warning("expired card update failed hitl_id=%s err=%s", hitl_id, exc)

                    # Cleanup
                    if self._file_store is not None:
                        try:
                            await self._file_store.delete(f"hitl-lark-ws/{hitl_id}.json")
                        except Exception:
                            pass
                    self._hitl_message_ids.pop(hitl_id, None)
                    self._hitl_requests.pop(hitl_id, None)
                    self._hitl_session_ids.pop(hitl_id, None)

            except Exception as exc:
                logger.error("expiration poll error err=%s", exc, exc_info=True)

    # ── Lifecycle ────────────────────────────────────────────────

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        loop = asyncio.get_running_loop()
        self._app_loop = loop
        self._expiration_task = asyncio.ensure_future(self._expiration_poll_loop())

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
                logger.info("WS client built, calling start()")
                client.start()
            except Exception as exc:
                logger.error("WS thread failed err=%s", exc, exc_info=True)

        self._ws_thread = threading.Thread(target=_run_ws, daemon=True)
        self._ws_thread.start()
        logger.info("started WS long connection")

    async def stop(self) -> None:
        if self._expiration_task is not None:
            self._expiration_task.cancel()
            self._expiration_task = None
        self._started = False
        logger.info("stopped")

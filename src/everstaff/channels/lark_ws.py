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
        allowed_emails: list[str] | None = None,
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
        self._allowed_emails: set[str] = set(allowed_emails) if allowed_emails else set()
        self._pending_agent_selection: dict[str, dict] = {}
        self._session_index = None
        self._mcp_pool = None
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

    async def _send_message(
        self,
        token: str,
        receive_id: str,
        msg_type: str,
        content: str,
        *,
        receive_id_type: str = "chat_id",
        reply_to: str | None = None,
    ) -> str:
        """Send a text or interactive message. Uses reply API when reply_to is set."""
        import aiohttp

        if reply_to:
            url = f"{self._api_base}/im/v1/messages/{reply_to}/reply"
            body = {"msg_type": msg_type, "content": content}
        else:
            url = f"{self._api_base}/im/v1/messages?receive_id_type={receive_id_type}"
            body = {"receive_id": receive_id, "msg_type": msg_type, "content": content}
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        logger.info("POST url=%s body=%s", url, json.dumps(body, ensure_ascii=False))
        async with aiohttp.ClientSession() as s:
            async with s.post(url, headers=headers, json=body) as r:
                data = await r.json()
                logger.info("POST response status=%s resp=%s", r.status, json.dumps(data, ensure_ascii=False))
                mid = data.get("data", {}).get("message_id", "")
                if not mid:
                    logger.error("send_message failed code=%s msg=%s", data.get("code"), data.get("msg"))
                return mid

    async def _delete_message(self, token: str, message_id: str) -> None:
        """Recall/delete a bot message."""
        import aiohttp

        url = f"{self._api_base}/im/v1/messages/{message_id}"
        headers = {"Authorization": f"Bearer {token}"}
        logger.info("DELETE url=%s", url)
        async with aiohttp.ClientSession() as s:
            async with s.delete(url, headers=headers) as r:
                data = await r.json()
                logger.info("DELETE response status=%s resp=%s", r.status, json.dumps(data, ensure_ascii=False))

    async def _add_reaction(self, token: str, message_id: str, emoji_type: str = "OK") -> None:
        """Add an emoji reaction to a message."""
        import aiohttp

        url = f"{self._api_base}/im/v1/messages/{message_id}/reactions"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        body = {"reaction_type": {"emoji_type": emoji_type}}
        logger.info("POST url=%s body=%s", url, json.dumps(body, ensure_ascii=False))
        async with aiohttp.ClientSession() as s:
            async with s.post(url, headers=headers, json=body) as r:
                data = await r.json()
                logger.info("POST reaction response status=%s resp=%s", r.status, json.dumps(data, ensure_ascii=False))

    async def _get_message(self, token: str, message_id: str) -> dict:
        """Fetch a message by ID."""
        import aiohttp

        url = f"{self._api_base}/im/v1/messages/{message_id}"
        headers = {"Authorization": f"Bearer {token}"}
        logger.info("GET url=%s", url)
        async with aiohttp.ClientSession() as s:
            async with s.get(url, headers=headers) as r:
                data = await r.json()
                logger.info("GET message response status=%s resp=%s", r.status, json.dumps(data, ensure_ascii=False))
                return data.get("data", {})

    async def _resolve_email(self, open_id: str) -> str:
        """Resolve open_id to email via contact API. Cached with 'email:' prefix key."""
        cache_key = f"email:{open_id}"
        if cache_key in self._username_cache:
            return self._username_cache[cache_key]
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
                        logger.warning("resolve_email API error open_id=%s code=%s msg=%s", open_id, code, data.get("msg"))
                        self._username_cache[cache_key] = ""
                        return ""
                    email = data.get("data", {}).get("user", {}).get("email", "")
                    logger.info("resolve_email open_id=%s -> email=%s", open_id, email)
                    self._username_cache[cache_key] = email
                    return email
        except Exception as exc:
            logger.warning("resolve_email failed open_id=%s err=%s", open_id, exc)
            self._username_cache[cache_key] = ""
            return ""

    async def _check_whitelist(self, open_id: str, message_id: str | None = None) -> bool:
        """Check if user is in the allowed_emails whitelist.

        Returns True if whitelist is empty (disabled) or email is allowed.
        Adds THUMBSDOWN reaction if message_id is provided and user is denied.
        """
        if not self._allowed_emails:
            return True
        email = await self._resolve_email(open_id)
        if email in self._allowed_emails:
            return True
        logger.warning("whitelist denied open_id=%s email=%s", open_id, email)
        if message_id:
            try:
                token = await self._get_access_token()
                await self._add_reaction(token, message_id, emoji_type="THUMBSDOWN")
            except Exception as exc:
                logger.warning("whitelist reaction failed err=%s", exc)
        return False

    async def _load_conv_state(self, key: str) -> dict | None:
        """Read conversation state from file_store at lark-conv/{app_id}/{key}.json."""
        if self._file_store is None:
            return None
        try:
            raw = await self._file_store.read(f"lark-conv/{self._app_id}/{key}.json")
            return json.loads(raw.decode())
        except Exception:
            return None

    async def _save_conv_state(self, key: str, state: dict) -> None:
        """Write conversation state to file_store at lark-conv/{app_id}/{key}.json."""
        if self._file_store is None:
            return
        await self._file_store.write(
            f"lark-conv/{self._app_id}/{key}.json",
            json.dumps(state, ensure_ascii=False).encode(),
        )

    async def _delete_conv_state(self, key: str) -> None:
        """Delete conversation state from file_store."""
        if self._file_store is None:
            return
        try:
            await self._file_store.delete(f"lark-conv/{self._app_id}/{key}.json")
        except Exception:
            pass

    async def _create_chat_group(self, token: str, name: str, owner_open_id: str) -> str:
        """Create a new Lark group chat. Returns the chat_id."""
        import aiohttp

        url = f"{self._api_base}/im/v1/chats"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        body = {"name": name, "owner_id": owner_open_id, "user_id_type": "open_id"}
        logger.info("POST url=%s body=%s", url, json.dumps(body, ensure_ascii=False))
        async with aiohttp.ClientSession() as s:
            async with s.post(url, headers=headers, json=body) as r:
                data = await r.json()
                logger.info("POST create_chat response status=%s resp=%s", r.status, json.dumps(data, ensure_ascii=False))
                chat_id = data.get("data", {}).get("chat_id", "")
                if not chat_id:
                    logger.error("create_chat failed code=%s msg=%s", data.get("code"), data.get("msg"))
                return chat_id

    async def _add_chat_members(self, token: str, chat_id: str, open_ids: list[str]) -> None:
        """Add members to a Lark group chat."""
        import aiohttp

        url = f"{self._api_base}/im/v1/chats/{chat_id}/members"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        body = {"id_list": open_ids, "member_id_type": "open_id"}
        logger.info("POST url=%s body=%s", url, json.dumps(body, ensure_ascii=False))
        async with aiohttp.ClientSession() as s:
            async with s.post(url, headers=headers, json=body) as r:
                data = await r.json()
                logger.info("POST add_chat_members response status=%s resp=%s", r.status, json.dumps(data, ensure_ascii=False))

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

    async def _list_agents(self) -> list[dict]:
        """List available agents from builtin + user agents_dir. User agents override builtins by uuid."""
        from pathlib import Path
        from everstaff.utils.yaml_loader import load_yaml
        from everstaff.core.config import _builtin_agents_path

        agents_by_uuid: dict[str, dict] = {}

        # Collect builtin agents first
        builtin_path = _builtin_agents_path()
        if builtin_path:
            bp = Path(builtin_path)
            for f in sorted(bp.glob("*.yaml")):
                try:
                    spec = load_yaml(f)
                    uid = spec.get("uuid", f.stem)
                    agents_by_uuid[uid] = spec
                except Exception as exc:
                    logger.warning("skip builtin agent %s err=%s", f.name, exc)

        # Collect user agents (override by uuid)
        if self._config and self._config.agents_dir:
            user_dir = Path(self._config.agents_dir).expanduser().resolve()
            if user_dir.is_dir():
                for f in sorted(user_dir.glob("*.yaml")):
                    try:
                        spec = load_yaml(f)
                        uid = spec.get("uuid", f.stem)
                        agents_by_uuid[uid] = spec
                    except Exception as exc:
                        logger.warning("skip user agent %s err=%s", f.name, exc)

        return list(agents_by_uuid.values())

    def _build_agent_selection_card(self, agents: list[dict], requester_open_id: str) -> dict:
        """Build a Lark interactive card with a dropdown for agent selection."""
        options = []
        for agent in agents:
            name = agent.get("agent_name", "Unknown")
            desc = agent.get("description", "")[:50]
            uid = agent.get("uuid", name)
            options.append({
                "text": {"tag": "plain_text", "content": f"{name} - {desc}"},
                "value": json.dumps({"agent_name": name, "agent_uuid": uid}),
            })

        elements: list[dict] = [
            {
                "tag": "form",
                "name": "agent_selection_form",
                "elements": [
                    {
                        "tag": "select_static",
                        "name": "agent_choice",
                        "placeholder": {"tag": "plain_text", "content": "Choose an agent..."},
                        "options": options,
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "Start"},
                        "type": "primary",
                        "action_type": "form_submit",
                        "name": "submit",
                        "value": {"action": "select_agent", "requester": requester_open_id},
                    },
                ],
            },
        ]

        return {
            "config": {"wide_screen_mode": True, "update_multi": True},
            "header": {"title": {"tag": "plain_text", "content": f"[{self._bot_name}] Select Agent"}, "template": "blue"},
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

    def _build_reply_card(self, reply_text: str, session_id: str, agent_name: str, source_chat_id: str) -> dict:
        """Build a reply card with agent response and 'New Conversation' button."""
        elements: list[dict] = [
            {"tag": "div", "text": {"tag": "lark_md", "content": reply_text}},
            {"tag": "hr"},
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "New Conversation"},
                        "type": "primary",
                        "value": {
                            "action": "new_conversation",
                            "session_id": session_id,
                            "agent_name": agent_name,
                            "source_chat_id": source_chat_id,
                        },
                    },
                ],
            },
        ]

        short_id = session_id[:8].upper()
        if self._web_url:
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": f"[Session {short_id}]({self._web_url}/sessions/{session_id})"}})

        return {
            "config": {"wide_screen_mode": True, "update_multi": True},
            "header": {"title": {"tag": "plain_text", "content": f"[{self._bot_name}] {agent_name}"}, "template": "green"},
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

    # ── Conversation message handling ─────────────────────────

    async def _send_card_to(self, token: str, chat_id: str, card: dict) -> str:
        """Send an interactive card to any chat. Returns message_id."""
        import aiohttp

        url = f"{self._api_base}/im/v1/messages?receive_id_type=chat_id"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        body = {"receive_id": chat_id, "msg_type": "interactive", "content": json.dumps(card)}
        logger.info("POST url=%s body=%s", url, json.dumps(body, ensure_ascii=False))
        async with aiohttp.ClientSession() as s:
            async with s.post(url, headers=headers, json=body) as r:
                data = await r.json()
                logger.info("POST response status=%s resp=%s", r.status, json.dumps(data, ensure_ascii=False))
                mid = data.get("data", {}).get("message_id", "")
                if not mid:
                    logger.error("send_card_to failed code=%s msg=%s", data.get("code"), data.get("msg"))
                return mid

    async def _handle_private_message(self, open_id: str, text: str, message_id: str, chat_id: str) -> None:
        """Handle a private (p2p) message from a user."""
        conv_key = f"private/{open_id}"

        # /new command: reset conversation state
        if text.strip().lower() == "/new":
            await self._delete_conv_state(conv_key)
            # Fall through to agent selection below

        # Check for existing active session
        if text.strip().lower() != "/new":
            state = await self._load_conv_state(conv_key)
            if state and state.get("session_id"):
                await self._send_to_session(
                    session_id=state["session_id"],
                    agent_name=state.get("agent_name", ""),
                    agent_uuid=state.get("agent_uuid", ""),
                    text=text,
                    message_id=message_id,
                    chat_id=chat_id,
                    reply_to=None,
                )
                return

        # No active session — show agent selection
        agents = await self._list_agents()
        if not agents:
            token = await self._get_access_token()
            await self._send_message(token, chat_id, "text", json.dumps({"text": "No agents available."}))
            return

        self._pending_agent_selection[open_id] = {
            "text": text,
            "message_id": message_id,
            "chat_id": chat_id,
            "chat_type": "p2p",
        }
        token = await self._get_access_token()
        card = self._build_agent_selection_card(agents, open_id)
        sel_mid = await self._send_card_to(token, chat_id, card)
        if sel_mid:
            self._pending_agent_selection[open_id]["selection_message_id"] = sel_mid
        logger.info("sent agent selection card to open_id=%s mid=%s", open_id, sel_mid)

    async def _handle_group_message(
        self,
        open_id: str,
        text: str,
        message_id: str,
        chat_id: str,
        parent_id: str = "",
    ) -> None:
        """Handle a group chat message where bot was @mentioned."""
        logger.info("handle_group open_id=%s chat=%s text=%s parent=%s", open_id, chat_id, text[:100], parent_id)

        # Fetch quoted message content if present
        full_text = text
        if parent_id:
            try:
                token = await self._get_access_token()
                msg_data = await self._get_message(token, parent_id)
                items = msg_data.get("items", [])
                if items:
                    quoted_content = items[0].get("body", {}).get("content", "")
                    try:
                        quoted_parsed = json.loads(quoted_content)
                        quoted_text = quoted_parsed.get("text", "")
                    except (json.JSONDecodeError, TypeError):
                        quoted_text = quoted_content
                    if quoted_text:
                        full_text = f"[Quoted]\n{quoted_text}\n\n[Message]\n{text}"
            except Exception as exc:
                logger.warning("fetch quoted message failed parent=%s err=%s", parent_id, exc)

        # Check if this is a spawned conversation group (acts like private chat)
        state = await self._load_conv_state(f"group/{chat_id}")
        if state and state.get("is_conversation_group"):
            await self._send_to_session(
                session_id=state["session_id"],
                agent_name=state.get("agent_name", ""),
                agent_uuid=state.get("agent_uuid", ""),
                text=full_text,
                message_id=message_id,
                chat_id=chat_id,
                reply_to=None,  # in spawned group, reply as new message
            )
            return

        # Always show agent selection for group chats (every @bot is a new session)
        agents = await self._list_agents()
        if not agents:
            token = await self._get_access_token()
            await self._send_message(
                token, chat_id, "text",
                json.dumps({"text": "No agents available."}),
                reply_to=message_id,
            )
            return

        # Store pending context
        self._pending_agent_selection[open_id] = {
            "text": full_text,
            "message_id": message_id,
            "chat_id": chat_id,
            "chat_type": "group",
            "reply_to": message_id,
        }

        # Send agent selection card
        token = await self._get_access_token()
        card = self._build_agent_selection_card(agents, open_id)
        mid = await self._send_card_to(token, chat_id, card)
        if mid:
            self._pending_agent_selection[open_id]["selection_card_id"] = mid

    async def _send_to_session(
        self,
        session_id: str,
        agent_name: str,
        agent_uuid: str,
        text: str,
        message_id: str,
        chat_id: str,
        reply_to: str | None = None,
    ) -> None:
        """Send user text to an existing session and relay the agent reply."""
        try:
            token = await self._get_access_token()
            await self._add_reaction(token, message_id, emoji_type="OK")
        except Exception as exc:
            logger.warning("send_to_session reaction failed err=%s", exc)

        try:
            from everstaff.api.sessions import _resume_session_task

            await _resume_session_task(
                session_id=session_id,
                agent_name=agent_name,
                decision_text=text,
                config=self._config,
                channel_manager=self._channel_manager,
                agent_uuid=agent_uuid,
                mcp_pool=self._mcp_pool,
                session_index=self._session_index,
            )

            reply_text = await self._read_session_reply(session_id)
            token = await self._get_access_token()

            if reply_to:
                # Group: reply as card
                reply_card = {
                    "config": {"wide_screen_mode": True},
                    "header": {"title": {"tag": "plain_text", "content": f"[{self._bot_name}]"}, "template": "blue"},
                    "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": reply_text}}],
                }
                await self._send_message(
                    token, chat_id, "interactive", json.dumps(reply_card),
                    reply_to=reply_to,
                )
            else:
                # Private: send text message
                await self._send_message(
                    token, chat_id, "text", json.dumps({"text": reply_text}),
                )
        except Exception as exc:
            logger.error("send_to_session failed session=%s err=%s", session_id, exc, exc_info=True)
            try:
                token = await self._get_access_token()
                await self._send_message(
                    token, chat_id, "text",
                    json.dumps({"text": f"Error: {exc}"}),
                )
            except Exception as inner_exc:
                logger.error("send_to_session error message failed err=%s", inner_exc)

    async def _read_session_reply(self, session_id: str) -> str:
        """Read the last assistant message from a session's session.json."""
        from pathlib import Path

        if not self._config:
            return "No response from agent."

        session_path = Path(self._config.sessions_dir).expanduser().resolve() / session_id / "session.json"
        try:
            with open(session_path) as f:
                session_data = json.load(f)

            messages = session_data.get("messages", [])
            # Find last assistant message
            for msg in reversed(messages):
                if msg.get("role") == "assistant":
                    content = msg.get("content", "")
                    if isinstance(content, str) and content:
                        return content
                    if isinstance(content, list):
                        # Extract text parts
                        parts = []
                        for part in content:
                            if isinstance(part, dict) and part.get("type") == "text":
                                parts.append(part.get("text", ""))
                            elif isinstance(part, str):
                                parts.append(part)
                        if parts:
                            return "\n".join(parts)
            return "No response from agent."
        except Exception as exc:
            logger.warning("read_session_reply failed session=%s err=%s", session_id, exc)
            return "No response from agent."

    # ── Message routing ────────────────────────────────────────

    async def _route_message(
        self,
        chat_type: str,
        chat_id: str,
        open_id: str,
        text: str,
        message_id: str,
        parent_id: str = "",
        is_mentioned: bool = False,
    ) -> None:
        """Route an incoming message to the appropriate handler."""
        # Check whitelist first
        if not await self._check_whitelist(open_id, message_id):
            return

        if chat_type == "p2p":
            await self._handle_private_message(open_id, text, message_id, chat_id)
        elif chat_type == "group" and is_mentioned:
            await self._handle_group_message(open_id, text, message_id, chat_id, parent_id)
        else:
            logger.debug("ignoring message chat_type=%s mentioned=%s", chat_type, is_mentioned)

    async def _handle_agent_selected(self, open_id: str, agent_name: str, agent_uuid: str) -> None:
        """Handle agent selection from the card callback."""
        import uuid as _uuid

        pending = self._pending_agent_selection.pop(open_id, None)
        if not pending:
            logger.warning("handle_agent_selected no pending context for open_id=%s", open_id)
            return

        # Delete the selection card
        selection_mid = pending.get("selection_message_id")
        if selection_mid:
            try:
                token = await self._get_access_token()
                await self._delete_message(token, selection_mid)
            except Exception as exc:
                logger.warning("handle_agent_selected delete card failed err=%s", exc)

        chat_id = pending["chat_id"]
        chat_type = pending.get("chat_type", "p2p")
        text = pending.get("text", "")
        message_id = pending.get("message_id", "")
        parent_id = pending.get("parent_id", "")

        # Create new session
        session_id = str(_uuid.uuid4())

        # Save conversation state
        if chat_type == "p2p":
            conv_key = f"private/{open_id}"
        else:
            conv_key = f"group/{chat_id}"

        await self._save_conv_state(conv_key, {
            "session_id": session_id,
            "agent_name": agent_name,
            "agent_uuid": agent_uuid,
            "open_id": open_id,
            "chat_id": chat_id,
            "chat_type": chat_type,
        })

        # Send the pending message to the new session
        reply_to = (parent_id or message_id) if chat_type == "group" else None
        await self._send_to_session(
            session_id=session_id,
            agent_name=agent_name,
            agent_uuid=agent_uuid,
            text=text,
            message_id=message_id,
            chat_id=chat_id,
            reply_to=reply_to,
        )

    async def _handle_new_conversation(
        self,
        open_id: str,
        agent_name: str,
        source_session_id: str,
        source_chat_id: str,
    ) -> None:
        """Create a new Lark group for continued conversation."""
        logger.info("new_conversation open_id=%s agent=%s", open_id, agent_name)
        try:
            token = await self._get_access_token()

            # Resolve username for group name
            username = await self._resolve_username(open_id)
            group_name = f"{self._bot_name} - {username} - {agent_name}"

            # Create group
            new_chat_id = await self._create_chat_group(token, group_name, open_id)
            if not new_chat_id:
                logger.error("failed to create chat group")
                return

            # Add user to group
            await self._add_chat_members(token, new_chat_id, [open_id])

            # Create a new session for this group
            from uuid import uuid4
            session_id = str(uuid4())

            # Load agent_uuid from agents list
            agent_uuid = ""
            agents = await self._list_agents()
            for a in agents:
                if a.get("agent_name") == agent_name:
                    agent_uuid = a.get("uuid", "")
                    break

            # Persist group state
            await self._save_conv_state(f"group/{new_chat_id}", {
                "session_id": session_id,
                "agent_name": agent_name,
                "agent_uuid": agent_uuid,
                "is_conversation_group": True,
            })

            # Send welcome message
            welcome = f"Conversation started with **{agent_name}**. Send messages directly to chat."
            await self._send_message(token, new_chat_id, "text", json.dumps({"text": welcome}))

        except Exception as exc:
            logger.error("new_conversation failed err=%s", exc, exc_info=True)

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
        from lark_oapi.api.im.v1 import P2ImMessageReceiveV1
        from lark_oapi.ws.enum import MessageType
        from lark_oapi.ws.const import (
            HEADER_TYPE, HEADER_MESSAGE_ID, HEADER_TRACE_ID,
            HEADER_SUM, HEADER_SEQ, HEADER_BIZ_RT,
        )
        from lark_oapi.ws.model import Response as WsResp
        from lark_oapi.core.const import UTF_8

        def message_handler(data: P2ImMessageReceiveV1):
            """Handle incoming im.message.receive_v1 events."""
            try:
                event = data.event
                message = event.message
                sender = event.sender

                chat_type = message.chat_type  # "p2p" or "group"
                chat_id = message.chat_id
                message_id = message.message_id
                open_id = sender.sender_id.open_id
                parent_id = message.parent_id or ""

                # Extract text content
                text = ""
                if message.message_type == "text":
                    try:
                        content = json.loads(message.content)
                        text = content.get("text", "")
                    except (json.JSONDecodeError, TypeError):
                        text = ""

                # Check for @bot mentions and strip them from text
                is_mentioned = False
                mentions = message.mentions or []
                for mention in mentions:
                    if mention.id and mention.id.user_id:
                        pass  # regular user mention
                    # Bot mentions have name matching bot_name
                    if mention.name == self._bot_name or mention.key:
                        is_mentioned = True
                        # Strip @mention from text
                        if mention.key:
                            text = text.replace(mention.key, "").strip()

                logger.info(
                    "message_handler chat_type=%s chat_id=%s open_id=%s text=%r message_id=%s parent_id=%s mentioned=%s",
                    chat_type, chat_id, open_id, text, message_id, parent_id, is_mentioned,
                )

                if self._app_loop is not None and self._app_loop.is_running():
                    asyncio.run_coroutine_threadsafe(
                        self._route_message(chat_type, chat_id, open_id, text, message_id, parent_id, is_mentioned),
                        self._app_loop,
                    )
                else:
                    logger.error("message_handler app loop unavailable, message dropped")
            except Exception as exc:
                logger.error("message_handler failed err=%s", exc, exc_info=True)

        def sync_card_handler(data: P2CardActionTrigger):
            """Parse card action and dispatch resolution to the app event loop.

            Returns a toast response for immediate user feedback.
            Card update to "Resolved" state is handled by on_resolved() via broadcast.
            """
            logger.info("sync_card_handler entered")

            # ── Check for agent selection action BEFORE HITL handling ──
            event = getattr(data, "event", data)
            action = getattr(event, "action", None)
            if action is not None:
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

                if value.get("action") == "select_agent":
                    requester_open_id = value.get("requester", "")
                    operator = getattr(event, "operator", None)
                    clicker_open_id = getattr(operator, "open_id", "") if operator else ""

                    if requester_open_id and clicker_open_id and requester_open_id != clicker_open_id:
                        logger.warning("agent selection requester mismatch requester=%s clicker=%s", requester_open_id, clicker_open_id)
                        return {"toast": {"type": "info", "content": "Only the requester can select an agent."}}

                    # Extract agent choice from form_value
                    raw_form = getattr(action, "form_value", None)
                    if isinstance(raw_form, str):
                        try:
                            form_dict = json.loads(raw_form)
                        except (json.JSONDecodeError, TypeError):
                            form_dict = {}
                    elif isinstance(raw_form, dict):
                        form_dict = raw_form
                    else:
                        form_dict = {}

                    agent_choice_raw = form_dict.get("agent_choice", "")
                    if isinstance(agent_choice_raw, str):
                        try:
                            agent_choice = json.loads(agent_choice_raw)
                        except (json.JSONDecodeError, TypeError):
                            agent_choice = {}
                    elif isinstance(agent_choice_raw, dict):
                        agent_choice = agent_choice_raw
                    else:
                        agent_choice = {}

                    agent_name = agent_choice.get("agent_name", "")
                    agent_uuid = agent_choice.get("agent_uuid", "")
                    logger.info("sync_card_handler agent selection agent_name=%s agent_uuid=%s open_id=%s", agent_name, agent_uuid, requester_open_id or clicker_open_id)

                    if agent_name and self._app_loop is not None and self._app_loop.is_running():
                        asyncio.run_coroutine_threadsafe(
                            self._handle_agent_selected(requester_open_id or clicker_open_id, agent_name, agent_uuid),
                            self._app_loop,
                        )

                    return {"toast": {"type": "success", "content": f"Starting {agent_name}..."}}

                if value.get("action") == "new_conversation":
                    operator = getattr(event, "operator", None)
                    clicker_open_id = getattr(operator, "open_id", "") if operator else ""
                    session_id = value.get("session_id", "")
                    agent_name = value.get("agent_name", "")
                    source_chat_id = value.get("source_chat_id", "")

                    if self._app_loop is not None and self._app_loop.is_running():
                        asyncio.run_coroutine_threadsafe(
                            self._handle_new_conversation(clicker_open_id, agent_name, session_id, source_chat_id),
                            self._app_loop,
                        )

                    return {"toast": {"type": "success", "content": "Creating new conversation group..."}}

            # ── HITL handling (existing logic) ──
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
            .register_p2_im_message_receive_v1(message_handler)
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

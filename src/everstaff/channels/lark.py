"""Lark/Feishu HITL channel — sends interactive cards, receives button callbacks."""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from everstaff.protocols import HitlRequest, HitlResolution

logger = logging.getLogger(__name__)

_DOMAIN_TO_API_BASE = {
    "feishu": "https://open.feishu.cn/open-apis",
    "lark": "https://open.larksuite.com/open-apis",
}


class LarkChannel:
    """
    HITL channel for Lark/Feishu using HTTP webhooks.

    Outbound: POST interactive cards to a Lark chat.
    Inbound:  Lark POSTs card-action callbacks to POST /webhooks/lark.
    """

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        verification_token: str,
        chat_id: str = "",
        bot_name: str = "Agent",
        file_store=None,
        domain: str = "feishu",
    ) -> None:
        self._app_id = app_id
        self._app_secret = app_secret
        self._verification_token = verification_token
        self._chat_id = chat_id
        self._bot_name = bot_name
        self._api_base = _DOMAIN_TO_API_BASE.get(domain, _DOMAIN_TO_API_BASE["feishu"])
        self._hitl_message_ids: dict[str, str] = {}
        self._hitl_requests: dict[str, "HitlRequest"] = {}
        self._file_store = file_store

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
                    logger.error("LarkChannel: send failed code=%s msg=%s", data.get("code"), data.get("msg"))
                return mid

    async def _update_card(self, token: str, message_id: str, card: dict) -> None:
        import aiohttp

        url = f"{self._api_base}/im/v1/messages/{message_id}"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        async with aiohttp.ClientSession() as s:
            async with s.patch(url, headers=headers, json={"msg_type": "interactive", "content": json.dumps(card)}) as r:
                if r.status >= 400:
                    logger.warning("LarkChannel: update card %s failed HTTP %s", message_id, r.status)

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
        elif request.type == "tool_permission":
            # Show tool details
            if request.tool_name:
                elements.append({"tag": "div", "text": {"tag": "plain_text", "content": f"Tool: {request.tool_name}"}})
            if request.tool_args:
                args_text = json.dumps(request.tool_args, ensure_ascii=False, indent=2)
                if len(args_text) > 500:
                    args_text = args_text[:500] + "..."
                elements.append({"tag": "div", "text": {"tag": "plain_text", "content": f"Arguments:\n{args_text}"}})
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

        return {
            "config": {"wide_screen_mode": True, "update_multi": True},
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
        if request.type == "notify":
            try:
                token = await self._get_access_token()
                await self._send_card(token, self._build_notify_card(request))
            except Exception as exc:
                logger.error("LarkChannel.send_request notify failed %s: %s", request.hitl_id, exc)
            return

        self._hitl_requests[request.hitl_id] = request
        try:
            token = await self._get_access_token()
            mid = await self._send_card(token, self._build_card(request, request.hitl_id))
            if mid:
                if self._file_store is not None:
                    await self._file_store.write(
                        f"hitl-lark/{request.hitl_id}.json",
                        json.dumps({"hitl_id": request.hitl_id, "message_id": mid}).encode(),
                    )
                else:
                    self._hitl_message_ids[request.hitl_id] = mid
                logger.info("LarkChannel: sent card %s mid=%s", request.hitl_id, mid)
        except Exception as exc:
            logger.error("LarkChannel.send_request failed %s: %s", request.hitl_id, exc)

    async def on_resolved(self, hitl_id: str, resolution: "HitlResolution") -> None:
        if self._file_store is not None:
            try:
                raw = await self._file_store.read(f"hitl-lark/{hitl_id}.json")
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
                    f"Resolved At: {resolution.resolved_at.strftime('%Y-%m-%d %H:%M UTC')}"
                )}}],
            }
            await self._update_card(token, message_id, card)
        except Exception as exc:
            logger.error("LarkChannel.on_resolved failed %s: %s", hitl_id, exc)
        finally:
            if self._file_store is not None:
                try:
                    await self._file_store.delete(f"hitl-lark/{hitl_id}.json")
                except Exception:
                    pass
            self._hitl_message_ids.pop(hitl_id, None)
            self._hitl_requests.pop(hitl_id, None)

    def verify_webhook(self, token: str) -> bool:
        return token == self._verification_token

    async def start(self) -> None:
        logger.info("LarkChannel ready — webhook endpoint: POST /webhooks/lark")

    async def stop(self) -> None:
        pass

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
    HITL channel for Lark/Feishu.

    Flow:
    1. send_request() → get access token → send interactive card to Lark chat
    2. User clicks card button → Lark POSTs callback to POST /webhooks/lark
    3. Webhook handler calls channel_manager.resolve()
    4. on_resolved() → update card to show resolved status
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
        self._hitl_message_ids: dict[str, str] = {}   # hitl_id → lark message_id
        self._hitl_requests: dict[str, "HitlRequest"] = {}  # hitl_id → original request
        self._file_store = file_store  # FileStore | None

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

    async def send_request(self, session_id: str, request: "HitlRequest") -> None:
        if request.type == "notify":
            try:
                token = await self._get_access_token()
                card = self._build_notify_card(request)
                await self._send_card(token, card)
            except Exception as exc:
                logger.error(
                    "LarkChannel.send_request (notify) failed for %s: %s",
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
                        f"hitl-lark/{request.hitl_id}.json",
                        json.dumps({"hitl_id": request.hitl_id, "message_id": message_id}).encode(),
                    )
                else:
                    self._hitl_message_ids[request.hitl_id] = message_id
                logger.info(
                    "LarkChannel: sent HITL card for %s, message_id=%s",
                    request.hitl_id, message_id,
                )
            else:
                logger.warning("LarkChannel: _send_card returned no message_id for %s", request.hitl_id)
        except Exception as exc:
            logger.error("LarkChannel.send_request failed for %s: %s", request.hitl_id, exc)

    async def on_resolved(self, hitl_id: str, resolution: "HitlResolution") -> None:
        if self._file_store is not None:
            try:
                raw = await self._file_store.read(f"hitl-lark/{hitl_id}.json")
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
            logger.error("LarkChannel.on_resolved failed for %s: %s", hitl_id, exc)
        finally:
            if self._file_store is not None:
                try:
                    await self._file_store.delete(f"hitl-lark/{hitl_id}.json")
                except Exception:
                    pass
            self._hitl_message_ids.pop(hitl_id, None)
            self._hitl_requests.pop(hitl_id, None)

    def verify_webhook(self, token: str) -> bool:
        """Verify incoming Lark webhook request using verification token."""
        return token == self._verification_token

    async def start(self) -> None:
        logger.info("LarkChannel ready — webhook endpoint: POST /webhooks/lark")

    async def stop(self) -> None:
        pass

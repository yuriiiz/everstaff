"""Feishu auth handler -- bridges tool auth errors with Lark channel card sending."""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class FeishuAuthHandler:
    """Wraps a LarkWsChannel to provide card-sending for auto-auth flow.

    When *user_open_id* is provided, cards and text messages are sent
    directly to the user's private chat (``receive_id_type=open_id``).
    Otherwise falls back to the channel's default ``chat_id``.
    """

    def __init__(self, channel: Any, user_open_id: str = "") -> None:
        self._channel = channel
        self._user_open_id = user_open_id

    # ------------------------------------------------------------------

    async def _send_message(self, msg_type: str, content: str) -> str:
        """Low-level send: prefer user open_id, fall back to channel chat_id."""
        conn = self._channel._connection
        if self._user_open_id:
            return await self._send_by_open_id(conn, msg_type, content)
        # Fallback: channel's default chat
        if msg_type == "interactive":
            return await conn.send_card(self._channel._chat_id, json.loads(content))
        return await conn.send_text(self._channel._chat_id, json.loads(content).get("text", ""))

    async def _send_by_open_id(self, conn: Any, msg_type: str, content: str) -> str:
        """Send a message using receive_id_type=open_id."""
        import aiohttp
        token = await conn.get_access_token()
        url = f"{conn._api_base}/im/v1/messages?receive_id_type=open_id"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        body = {"receive_id": self._user_open_id, "msg_type": msg_type, "content": content}
        logger.info("auth_handler send open_id=%s type=%s", self._user_open_id, msg_type)
        async with aiohttp.ClientSession() as s:
            async with s.post(url, headers=headers, json=body) as r:
                data = await r.json()
                mid = data.get("data", {}).get("message_id", "")
                if not mid:
                    logger.error("auth_handler send failed code=%s msg=%s",
                                 data.get("code"), data.get("msg"))
                return mid

    # ------------------------------------------------------------------

    async def send_card(self, card: dict) -> str:
        """Send an interactive card, return message_id."""
        return await self._send_message("interactive", json.dumps(card))

    async def update_card(self, message_id: str, card: dict) -> None:
        """Update an existing card via the channel's connection."""
        await self._channel._connection.update_card(message_id, card)

    async def send_text(self, text: str) -> str:
        """Send a plain text message, return message_id."""
        return await self._send_message("text", json.dumps({"text": text}))

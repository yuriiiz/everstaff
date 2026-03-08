"""LarkChannelAdapter — wraps LarkWsConnection HTTP methods as a ChannelAdapter."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from everstaff.channels.lark_ws_connection import LarkWsConnection

logger = logging.getLogger(__name__)


class LarkChannelAdapter:
    """ChannelAdapter implementation for Lark/Feishu."""

    def __init__(self, connection: "LarkWsConnection") -> None:
        self._conn = connection

    async def send_text(self, chat_id: str, text: str) -> str:
        return await self._conn.send_text(chat_id, text)

    async def send_card(self, chat_id: str, card: dict) -> str:
        return await self._conn.send_card(chat_id, card)

    async def update_card(self, message_id: str, card: dict) -> None:
        return await self._conn.update_card(message_id, card)

    async def delete_message(self, message_id: str) -> None:
        import aiohttp
        token = await self._conn.get_access_token()
        url = f"{self._conn._api_base}/im/v1/messages/{message_id}"
        headers = {"Authorization": f"Bearer {token}"}
        async with aiohttp.ClientSession() as s:
            async with s.delete(url, headers=headers) as r:
                if r.status != 200:
                    data = await r.json()
                    logger.warning("delete_message failed mid=%s status=%s msg=%s",
                                   message_id, r.status, data.get("msg"))

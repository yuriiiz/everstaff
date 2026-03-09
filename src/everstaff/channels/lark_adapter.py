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

    async def resolve_username(self, open_id: str) -> str:
        import aiohttp
        token = await self._conn.get_access_token()
        url = f"{self._conn._api_base}/contact/v3/users/{open_id}?user_id_type=open_id"
        headers = {"Authorization": f"Bearer {token}"}
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(url, headers=headers) as r:
                    data = await r.json()
                    if data.get("code", 0) != 0:
                        return open_id
                    return data.get("data", {}).get("user", {}).get("name", open_id)
        except Exception:
            return open_id

    async def create_chat_group(self, name: str, owner_open_id: str) -> str:
        import aiohttp
        token = await self._conn.get_access_token()
        url = f"{self._conn._api_base}/im/v1/chats"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        body = {"name": name, "owner_id": owner_open_id, "user_id_type": "open_id"}
        async with aiohttp.ClientSession() as s:
            async with s.post(url, headers=headers, json=body) as r:
                data = await r.json()
                chat_id = data.get("data", {}).get("chat_id", "")
                if not chat_id:
                    logger.warning("create_chat_group failed code=%s msg=%s", data.get("code"), data.get("msg"))
                return chat_id

    async def add_chat_members(self, chat_id: str, open_ids: list[str]) -> None:
        import aiohttp
        token = await self._conn.get_access_token()
        url = f"{self._conn._api_base}/im/v1/chats/{chat_id}/members"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        body = {"id_list": open_ids, "member_id_type": "open_id"}
        async with aiohttp.ClientSession() as s:
            async with s.post(url, headers=headers, json=body) as r:
                data = await r.json()
                if data.get("code", 0) != 0:
                    logger.warning("add_chat_members failed code=%s msg=%s", data.get("code"), data.get("msg"))

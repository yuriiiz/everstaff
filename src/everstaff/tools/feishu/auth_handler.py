"""Feishu auth handler -- bridges tool auth errors with Lark channel card sending."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class FeishuAuthHandler:
    """Wraps a LarkWsChannel to provide card-sending for auto-auth flow."""

    def __init__(self, channel: Any) -> None:
        self._channel = channel

    async def send_card(self, card: dict) -> str:
        """Send an interactive card via the channel's connection, return message_id."""
        return await self._channel._connection.send_card(self._channel._chat_id, card)

    async def update_card(self, message_id: str, card: dict) -> None:
        """Update an existing card via the channel's connection."""
        await self._channel._connection.update_card(message_id, card)

    async def send_text(self, text: str) -> str:
        """Send a plain text message via the channel's connection, return message_id."""
        return await self._channel._connection.send_text(self._channel._chat_id, text)

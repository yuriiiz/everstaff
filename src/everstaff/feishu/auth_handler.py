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
        """Send an interactive card via the channel, return message_id."""
        token = await self._channel._get_access_token()
        return await self._channel._send_card(token, card)

    async def update_card(self, message_id: str, card: dict) -> None:
        """Update an existing card."""
        token = await self._channel._get_access_token()
        await self._channel._update_card(token, message_id, card)

"""ChannelAdapter — abstract interface for channel message I/O."""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ChannelAdapter(Protocol):
    """Send/receive messages via a channel. Lark is the first implementation."""

    async def send_text(self, chat_id: str, text: str) -> str: ...
    async def send_card(self, chat_id: str, card: dict) -> str: ...
    async def update_card(self, message_id: str, card: dict) -> None: ...
    async def delete_message(self, message_id: str) -> None: ...

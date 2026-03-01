"""ChannelManager — broadcast HITL requests and coordinate resolution across channels."""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from everstaff.protocols import HitlChannel, HitlRequest, HitlResolution

logger = logging.getLogger(__name__)


class ChannelManager:
    """
    Broadcasts HITL requests to all registered channels.
    First channel to resolve wins; all others receive on_resolved() for cleanup.
    """

    def __init__(self) -> None:
        self._channels: list["HitlChannel"] = []
        self._resolved: set[str] = set()  # hitl_ids already resolved

    def register(self, channel: "HitlChannel") -> None:
        self._channels.append(channel)

    async def start_all(self) -> None:
        """Start all registered channels."""
        await asyncio.gather(*[ch.start() for ch in self._channels], return_exceptions=True)

    async def stop_all(self) -> None:
        """Stop all registered channels."""
        await asyncio.gather(*[ch.stop() for ch in self._channels], return_exceptions=True)

    async def broadcast(self, session_id: str, request: "HitlRequest") -> None:
        """Send HITL request to all channels."""
        if not self._channels:
            return
        results = await asyncio.gather(
            *[ch.send_request(session_id, request) for ch in self._channels],
            return_exceptions=True,
        )
        for ch, result in zip(self._channels, results):
            if isinstance(result, Exception):
                logger.warning("Channel %s failed to send request: %s", ch, result)

    async def resolve(self, hitl_id: str, resolution: "HitlResolution") -> bool:
        """
        Mark hitl_id as resolved. Idempotent — first caller wins.
        Returns True if this call resolved it, False if already resolved.
        Notifies all channels via on_resolved() regardless of who resolved.
        """
        if hitl_id in self._resolved:
            return False
        self._resolved.add(hitl_id)

        if not self._channels:
            return True

        results = await asyncio.gather(
            *[ch.on_resolved(hitl_id, resolution) for ch in self._channels],
            return_exceptions=True,
        )
        for ch, result in zip(self._channels, results):
            if isinstance(result, Exception):
                logger.warning("Channel %s failed on_resolved for %s: %s", ch, hitl_id, result)

        return True

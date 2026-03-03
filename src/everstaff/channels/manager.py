"""ChannelManager — broadcast HITL requests and coordinate resolution across channels."""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Callable, Awaitable, Optional

if TYPE_CHECKING:
    from everstaff.protocols import HitlChannel, HitlRequest, HitlResolution

logger = logging.getLogger(__name__)

# Callback signature: async (hitl_id, decision, comment, grant_scope) -> None
ResolveCallback = Callable[[str, str, Optional[str], Optional[str]], Awaitable[None]]


class ChannelManager:
    """
    Broadcasts HITL requests to all registered channels.
    First channel to resolve wins; all others receive on_resolved() for cleanup.
    After broadcast, calls ``_on_resolve`` to persist and resume the session.
    """

    def __init__(self) -> None:
        self._channels: list["HitlChannel"] = []
        self._resolved: set[str] = set()  # hitl_ids already resolved
        self._on_resolve: ResolveCallback | None = None

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
        Notifies all channels via on_resolved(), then persists via _on_resolve.
        """
        if hitl_id in self._resolved:
            return False
        self._resolved.add(hitl_id)

        # Broadcast to all channels
        if self._channels:
            results = await asyncio.gather(
                *[ch.on_resolved(hitl_id, resolution) for ch in self._channels],
                return_exceptions=True,
            )
            for ch, result in zip(self._channels, results):
                if isinstance(result, Exception):
                    logger.warning("Channel %s failed on_resolved for %s: %s", ch, hitl_id, result)

        # Persist resolution and resume session
        if self._on_resolve is not None:
            try:
                await self._on_resolve(hitl_id, resolution.decision, resolution.comment, getattr(resolution, "grant_scope", None))
            except Exception as exc:
                logger.error("ChannelManager._on_resolve failed for %s: %s", hitl_id, exc)

        return True

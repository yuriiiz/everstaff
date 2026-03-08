"""HitlRouter — route HITL requests to source entry first, fallback to broadcast."""
from __future__ import annotations

import logging
from typing import Any, Callable, Awaitable, TYPE_CHECKING

if TYPE_CHECKING:
    from everstaff.channels.manager import ChannelManager
    from everstaff.protocols import HitlRequest

logger = logging.getLogger(__name__)

HitlHandler = Callable[[str, "HitlRequest", dict[str, Any]], Awaitable[None]]


class HitlRouter:
    def __init__(self) -> None:
        self._handlers: dict[str, HitlHandler] = {}
        self._session_sources: dict[str, tuple[str, dict[str, Any]]] = {}
        self.channel_manager: ChannelManager | None = None

    def register_handler(self, source_type: str, handler: HitlHandler) -> None:
        self._handlers[source_type] = handler
        logger.info("registered HITL handler source_type=%s", source_type)

    def set_session_source(self, session_id: str, source_type: str, context: dict[str, Any] | None = None) -> None:
        self._session_sources[session_id] = (source_type, context or {})

    def clear_session(self, session_id: str) -> None:
        self._session_sources.pop(session_id, None)

    async def route(self, session_id: str, request: "HitlRequest") -> None:
        source = self._session_sources.get(session_id)
        if source is not None:
            source_type, context = source
            handler = self._handlers.get(source_type)
            if handler is not None:
                try:
                    await handler(session_id, request, context)
                    logger.info("HITL routed to source=%s session=%s hitl_id=%s", source_type, session_id[:8], request.hitl_id)
                    return
                except Exception as exc:
                    logger.warning("source handler failed source=%s err=%s, falling back", source_type, exc)

        if self.channel_manager is not None:
            await self.channel_manager.broadcast(session_id, request)
            logger.info("HITL fallback broadcast session=%s hitl_id=%s", session_id[:8], request.hitl_id)
        else:
            logger.warning("HITL unroutable: no source, no channel_manager session=%s hitl_id=%s", session_id[:8], request.hitl_id)

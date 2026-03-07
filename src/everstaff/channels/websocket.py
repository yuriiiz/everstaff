"""WebSocket HITL channel — uses existing /ws endpoint for push and receive."""
from __future__ import annotations

import logging
from typing import Callable, Awaitable, TYPE_CHECKING

if TYPE_CHECKING:
    from everstaff.protocols import HitlRequest, HitlResolution

logger = logging.getLogger(__name__)


class WebSocketChannel:
    """
    Sends HITL events to all connected WebSocket clients via a broadcast function.

    The broadcast_fn is provided by the API layer — it sends a dict payload
    to all active ws connections (or a specific session's connections).

    Incoming hitl_resolve messages from ws clients are handled in ws.py
    and routed to ChannelManager.resolve() directly.
    """

    def __init__(
        self,
        broadcast_fn: Callable[[dict], Awaitable[None]],
    ) -> None:
        self._broadcast = broadcast_fn

    async def send_request(self, session_id: str, request: "HitlRequest") -> None:
        """Push HITL request event to all connected WebSocket clients."""
        from datetime import datetime, timezone
        logger.info("hitl_request session=%s hitl=%s type=%s",
                    session_id[:8], request.hitl_id[:8], request.type)
        event = {
            "type": "hitl_request",
            "hitl_id": request.hitl_id,
            "session_id": session_id,
            "prompt": request.prompt,
            "hitl_type": request.type,
            "options": request.options,
            "context": request.context,
            "timeout_seconds": request.timeout_seconds,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "tool_name": request.tool_name,
            "tool_args": request.tool_args,
            "tool_permission_options": request.tool_permission_options,
        }
        await self._broadcast(event)

    async def on_resolved(self, hitl_id: str, resolution: "HitlResolution") -> None:
        """Broadcast HITL resolved event to all connected WebSocket clients."""
        logger.info("hitl_resolved hitl=%s decision=%s by=%s",
                    hitl_id[:8], resolution.decision, resolution.resolved_by)
        event = {
            "type": "hitl_resolved",
            "hitl_id": hitl_id,
            "decision": resolution.decision,
            "resolved_by": resolution.resolved_by,
        }
        await self._broadcast(event)

    async def start(self) -> None:
        """No-op: WebSocket server is started by FastAPI."""
        pass

    async def stop(self) -> None:
        """No-op: WebSocket server is stopped by FastAPI."""
        pass

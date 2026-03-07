"""ProxyTracer — forwards trace events over IPC as fire-and-forget notifications."""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from everstaff.protocols import TraceEvent

if TYPE_CHECKING:
    from everstaff.sandbox.ipc.channel import IpcChannel

logger = logging.getLogger(__name__)


class ProxyTracer:
    """TracingBackend that forwards all events over IPC to orchestrator.

    Uses fire-and-forget notifications for low latency.
    """

    def __init__(self, channel: "IpcChannel") -> None:
        self._channel = channel

    def on_event(self, event: TraceEvent) -> None:
        """Forward trace event as IPC notification (non-blocking)."""
        params = {
            "kind": event.kind,
            "session_id": event.session_id,
            "parent_session_id": event.parent_session_id,
            "timestamp": event.timestamp,
            "duration_ms": event.duration_ms,
            "data": event.data,
            "trace_id": event.trace_id,
            "span_id": event.span_id,
            "parent_span_id": event.parent_span_id,
        }
        asyncio.create_task(self._send(params))

    async def _send(self, params: dict) -> None:
        try:
            await self._channel.send_notification("tracer.event", params)
        except Exception:
            logger.debug("failed to send trace event via IPC", exc_info=True)

    async def aflush(self) -> None:
        """No-op: notifications are fire-and-forget."""

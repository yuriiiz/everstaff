"""ConsoleTracer — logs TraceEvents to the Python logging system."""
from __future__ import annotations

import logging

from everstaff.protocols import TraceEvent

logger = logging.getLogger(__name__)


class ConsoleTracer:
    """Emits trace events at INFO level so they are visible in normal CLI mode."""

    def on_event(self, event: TraceEvent) -> None:
        logger.info(
            "[%s] %s: %s",
            event.session_id[:8] if event.session_id else "????????",
            event.kind,
            event.data,
        )

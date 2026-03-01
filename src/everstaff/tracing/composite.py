"""CompositeTracer — fans out TraceEvents to multiple backends."""
from __future__ import annotations

import logging

from everstaff.protocols import TracingBackend, TraceEvent

logger = logging.getLogger(__name__)


class CompositeTracer:
    """Dispatches each TraceEvent to all registered backends.

    Backend exceptions are caught and logged; they never propagate to callers.
    """

    def __init__(self, backends: list[TracingBackend]) -> None:
        self._backends = backends

    def on_event(self, event: TraceEvent) -> None:
        for backend in self._backends:
            try:
                backend.on_event(event)
            except Exception as e:
                logger.warning(
                    "TracingBackend %s raised on event %s: %s",
                    type(backend).__name__,
                    event.kind,
                    e,
                )

    async def aflush(self) -> None:
        """Flush all backends that support async flushing."""
        for backend in self._backends:
            if hasattr(backend, "aflush"):
                try:
                    await backend.aflush()
                except Exception as e:
                    logger.warning(
                        "TracingBackend %s aflush failed: %s",
                        type(backend).__name__,
                        e,
                    )

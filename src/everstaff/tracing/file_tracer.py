"""FileTracer — buffers TraceEvents and flushes as JSONL to session and global files."""
from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

from everstaff.protocols import TraceEvent

if TYPE_CHECKING:
    from everstaff.protocols import FileStore

logger = logging.getLogger(__name__)


class FileTracer:
    """
    Buffers TraceEvents and flushes as JSONL lines to session and global files.

    Supports both FileStore injection (store=) and legacy Path-based construction.
    Buffer is flushed every `flush_interval` events, or when `flush_interval_seconds`
    seconds have elapsed since the last flush, or on explicit flush()/aflush().
    """

    FLUSH_INTERVAL_SECONDS = 1

    def __init__(
        self,
        session_path: "Path | str | None" = None,
        global_path: "Path | str | None" = None,
        *,
        store: "FileStore | None" = None,
        flush_interval: int = 50,
    ) -> None:
        self._flush_interval = flush_interval
        self._buffer: list[str] = []
        self._last_flush_time: float = time.monotonic()

        if store is not None:
            # New injection-based constructor: paths are relative strings
            self._store = store
            self._session_path: str | None = str(session_path) if session_path else None
            self._global_path: str | None = str(global_path) if global_path else None
            self._legacy_mode = False
        else:
            # Legacy Path-based construction — use direct file I/O for backward compat
            self._store = None
            self._legacy_session_path = Path(session_path) if session_path else None
            self._legacy_global_path = Path(global_path) if global_path else None
            self._legacy_mode = True

    def on_event(self, event: TraceEvent) -> None:
        try:
            line = json.dumps(dataclasses.asdict(event), ensure_ascii=False)
        except Exception as e:
            logger.warning("FileTracer failed to serialize event %s: %s", event.kind, e)
            return

        if self._legacy_mode:
            # Legacy: write immediately to preserve existing behavior (including failure isolation)
            for path in filter(None, [self._legacy_session_path, self._legacy_global_path]):
                try:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with path.open("a", encoding="utf-8") as f:
                        f.write(line + "\n")
                except Exception as e:
                    logger.warning(
                        "FileTracer failed to write event %s to %s: %s", event.kind, path, e
                    )
        else:
            # New buffered mode
            self._buffer.append(line)
            elapsed = time.monotonic() - self._last_flush_time
            if len(self._buffer) >= self._flush_interval or elapsed >= self.FLUSH_INTERVAL_SECONDS:
                # Can't await here; schedule async flush safely
                try:
                    loop = asyncio.get_running_loop()
                    lines = "\n".join(self._buffer) + "\n"
                    self._buffer.clear()
                    self._last_flush_time = time.monotonic()
                    loop.create_task(self._flush_async(lines))
                except RuntimeError:
                    self._flush_sync()

    def flush(self) -> None:
        """Flush buffered events (sync, only safe outside async context)."""
        if self._legacy_mode or not self._buffer:
            return
        try:
            asyncio.get_running_loop()
            # Running inside async context — cannot use asyncio.run()
            # Caller should use `await tracer.aflush()` instead
            logger.warning("FileTracer.flush() called from async context; use aflush() instead")
            return
        except RuntimeError:
            pass  # No running loop — safe to proceed
        self._flush_sync()

    def _flush_sync(self) -> None:
        if not self._buffer:
            return
        lines = "\n".join(self._buffer) + "\n"
        self._buffer.clear()
        self._last_flush_time = time.monotonic()
        asyncio.run(self._flush_async(lines))

    async def aflush(self) -> None:
        """Flush buffered events (async-safe version)."""
        if self._legacy_mode or not self._buffer:
            return
        lines = "\n".join(self._buffer) + "\n"
        self._buffer.clear()
        self._last_flush_time = time.monotonic()
        await self._flush_async(lines)

    async def _flush_async(self, lines: str) -> None:
        data = lines.encode()
        for path in filter(None, [self._session_path, self._global_path]):
            try:
                existing = b""
                if await self._store.exists(path):
                    existing = await self._store.read(path)
                await self._store.write(path, existing + data)
            except Exception as e:
                logger.warning("FileTracer failed to write to %s: %s", path, e)

    def close(self) -> None:
        """Flush remaining buffered events."""
        if not self._legacy_mode:
            self.flush()

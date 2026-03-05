"""ExecutorManager — manages sandbox executor lifecycle per session."""
from __future__ import annotations

import logging
import time
from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from everstaff.core.secret_store import SecretStore
    from everstaff.sandbox.executor import SandboxExecutor

logger = logging.getLogger(__name__)


class ExecutorManager:
    """Create, cache, and recycle sandbox executors per session."""

    def __init__(
        self,
        factory: Callable[[], "SandboxExecutor"],
        secret_store: "SecretStore",
        idle_timeout: float | None = None,
    ) -> None:
        self._factory = factory
        self._secret_store = secret_store
        self._executors: dict[str, "SandboxExecutor"] = {}
        self._idle_timeout = idle_timeout
        self._last_activity: dict[str, float] = {}

    async def get_or_create(self, session_id: str) -> "SandboxExecutor":
        self._last_activity[session_id] = time.monotonic()
        if session_id in self._executors:
            executor = self._executors[session_id]
            if executor.is_alive:
                return executor
            # Dead executor — remove and recreate
            del self._executors[session_id]

        executor = self._factory()
        await executor.start(session_id)
        self._executors[session_id] = executor
        logger.info("Created sandbox executor for session %s", session_id)
        return executor

    async def destroy(self, session_id: str) -> None:
        self._last_activity.pop(session_id, None)
        executor = self._executors.pop(session_id, None)
        if executor is not None:
            await executor.stop()
            logger.info("Destroyed sandbox executor for session %s", session_id)

    async def destroy_all(self) -> None:
        for session_id in list(self._executors):
            await self.destroy(session_id)

    def has_active(self, session_id: str) -> bool:
        """Check if a session has an active (alive) executor."""
        executor = self._executors.get(session_id)
        return executor is not None and executor.is_alive

    async def cleanup_idle(self) -> None:
        """Destroy executors that have been idle longer than idle_timeout."""
        if self._idle_timeout is None:
            return
        now = time.monotonic()
        to_destroy = [
            sid for sid, last in self._last_activity.items()
            if now - last > self._idle_timeout and sid in self._executors
        ]
        for sid in to_destroy:
            logger.info("Destroying idle executor for session %s", sid)
            await self.destroy(sid)

    @property
    def active_sessions(self) -> list[str]:
        return list(self._executors.keys())

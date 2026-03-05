"""ExecutorManager — manages sandbox executor lifecycle per session."""
from __future__ import annotations

import logging
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
    ) -> None:
        self._factory = factory
        self._secret_store = secret_store
        self._executors: dict[str, "SandboxExecutor"] = {}

    async def get_or_create(self, session_id: str) -> "SandboxExecutor":
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
        executor = self._executors.pop(session_id, None)
        if executor is not None:
            await executor.stop()
            logger.info("Destroyed sandbox executor for session %s", session_id)

    async def destroy_all(self) -> None:
        for session_id in list(self._executors):
            await self.destroy(session_id)

    @property
    def active_sessions(self) -> list[str]:
        return list(self._executors.keys())

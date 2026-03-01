"""LoopManager -- manages AgentLoop instances as asyncio.Tasks."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from everstaff.daemon.agent_loop import AgentLoop

logger = logging.getLogger(__name__)


class LoopManager:
    """Manages the lifecycle of multiple AgentLoop instances.

    Each loop is wrapped in an ``asyncio.Task`` and tracked by agent name.
    Provides start / stop / stop_all operations and status introspection.
    """

    def __init__(self) -> None:
        self._loops: dict[str, tuple[Any, asyncio.Task]] = {}  # agent_name -> (loop, task)

    async def start(self, loop: "AgentLoop") -> None:
        """Start an agent loop as an asyncio task.

        If a loop for the same agent name is already running it will be
        stopped first before the new one is started.
        """
        name = loop.agent_name
        if name in self._loops:
            logger.warning("Loop for '%s' already running, stopping first", name)
            await self.stop(name)
        task = asyncio.create_task(loop.run(), name=f"agent-loop-{name}")
        self._loops[name] = (loop, task)
        logger.info("Started loop for '%s'", name)

    async def stop(self, agent_name: str) -> None:
        """Stop a running agent loop by name.

        Calls ``loop.stop()`` to signal a graceful shutdown, then cancels
        the wrapping task and awaits its completion.
        """
        entry = self._loops.pop(agent_name, None)
        if entry is None:
            return
        loop, task = entry
        loop.stop()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        logger.info("Stopped loop for '%s'", agent_name)

    async def stop_all(self) -> None:
        """Stop all running agent loops."""
        names = list(self._loops.keys())
        for name in names:
            await self.stop(name)

    def has(self, agent_name: str) -> bool:
        """Return True if a loop is tracked for *agent_name*."""
        return agent_name in self._loops

    def get_status(self) -> dict[str, dict[str, Any]]:
        """Return a status dict keyed by agent name.

        Each entry contains:
        - ``running``: whether the loop reports itself as running.
        - ``task_done``: whether the underlying asyncio task has finished.
        """
        result: dict[str, dict[str, Any]] = {}
        for name, (loop, task) in self._loops.items():
            result[name] = {
                "running": loop.is_running,
                "task_done": task.done(),
            }
        return result

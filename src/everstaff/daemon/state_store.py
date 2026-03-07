"""DaemonStateStore — structured daemon state persistence via FileStore."""
from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from pydantic import BaseModel, Field

from everstaff.daemon.goals import GoalBreakdown

if TYPE_CHECKING:
    from everstaff.protocols import FileStore

logger = logging.getLogger(__name__)


class DaemonState(BaseModel):
    goals_breakdown: dict[str, GoalBreakdown] = Field(default_factory=dict)
    recent_decisions: list[dict[str, Any]] = Field(default_factory=list)


class DaemonStateStore:
    def __init__(self, store: "FileStore") -> None:
        self._store = store

    def _path(self, agent_uuid: str) -> str:
        return f"daemon/{agent_uuid}/state.json"

    async def load(self, agent_uuid: str) -> DaemonState:
        path = self._path(agent_uuid)
        if not await self._store.exists(path):
            return DaemonState()
        data = await self._store.read(path)
        return DaemonState.model_validate_json(data)

    async def save(self, agent_uuid: str, state: DaemonState) -> None:
        path = self._path(agent_uuid)
        await self._store.write(path, state.model_dump_json(indent=2).encode())

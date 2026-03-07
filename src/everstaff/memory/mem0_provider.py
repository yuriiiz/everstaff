"""Mem0Provider — PromptInjector that retrieves long-term memories."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from everstaff.memory.mem0_client import Mem0Client

logger = logging.getLogger(__name__)


class Mem0Provider:
    """Retrieves relevant memories from mem0 and injects them into the system prompt.

    Usage:
    1. set_query(latest_user_message)
    2. refresh() — async, calls mem0.search and caches result
    3. get_prompt_injection() — sync, returns cached formatted memories
    """

    def __init__(
        self,
        mem0_client: "Mem0Client",
        *,
        user_id: str | None = None,
        agent_id: str | None = None,
    ) -> None:
        self._client = mem0_client
        self._user_id = user_id
        self._agent_id = agent_id
        self._last_query: str = ""
        self._cached_injection: str = ""

    def set_query(self, query: str) -> None:
        self._last_query = query

    def get_prompt_injection(self) -> str:
        return self._cached_injection

    def get_tools(self) -> list:
        return []

    async def refresh(self) -> None:
        if not self._last_query:
            self._cached_injection = ""
            return
        try:
            scope = {}
            if self._user_id:
                scope["user_id"] = self._user_id
            if self._agent_id:
                scope["agent_id"] = self._agent_id
            results = await self._client.search(self._last_query, **scope)
        except Exception as exc:
            logger.warning("Mem0Provider: search failed: %s", exc)
            self._cached_injection = ""
            return

        if not results:
            self._cached_injection = ""
            return

        lines = [f"- {r['memory']}" for r in results]
        self._cached_injection = (
            "[Long-term memory]\n"
            "The following are relevant memories from previous interactions:\n"
            + "\n".join(lines)
        )

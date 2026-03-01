"""
NullObject and in-memory implementations for all optional protocols.
Used as defaults in AgentContext and in tests.
"""
from __future__ import annotations

from typing import Any

from everstaff.protocols import (
    Message, PermissionResult, Tool, ToolDefinition,
    ToolResult, TraceEvent,
)


class NullTracer:
    def on_event(self, event: TraceEvent) -> None:
        pass


class AllowAllChecker:
    def check(self, tool_name: str, args: dict[str, Any]) -> PermissionResult:
        return PermissionResult(allowed=True)


class DenyAllChecker:
    def check(self, tool_name: str, args: dict[str, Any]) -> PermissionResult:
        return PermissionResult(allowed=False, reason="deny-all policy")


class NullSkillProvider:
    def get_tools(self) -> list[Tool]:
        return []

    def get_prompt_injection(self) -> str:
        return ""


class NullKnowledgeProvider:
    def get_tools(self) -> list[Tool]:
        return []

    def get_prompt_injection(self) -> str:
        return ""


class NullSubAgentProvider:
    def get_tools(self) -> list[Tool]:
        return []

    def get_prompt_injection(self) -> str:
        return ""


class NullMcpProvider:
    def get_tools(self) -> list[Tool]:
        return []

    def get_prompt_injection(self) -> str:
        return ""

    async def aclose(self) -> None:
        pass


class InMemoryStore:
    """In-memory MemoryStore. Thread-safe enough for single-process tests."""

    def __init__(self) -> None:
        self._sessions: dict[str, list[Message]] = {}
        self._working: dict[str, "WorkingState"] = {}
        self._episodes: dict[str, list["Episode"]] = {}
        self._semantic: dict[str, dict[str, str]] = {}

    # L0: session messages

    async def load(self, session_id: str) -> list[Message]:
        return list(self._sessions.get(session_id, []))

    async def save(
        self,
        session_id: str,
        messages: list[Message],
        **kwargs: Any,
    ) -> None:
        self._sessions[session_id] = list(messages)

    # L1: working memory

    async def working_load(self, agent_id: str) -> "WorkingState":
        from everstaff.protocols import WorkingState
        return self._working.get(agent_id, WorkingState())

    async def working_save(self, agent_id: str, state: "WorkingState") -> None:
        self._working[agent_id] = state

    # L2: episodic memory

    async def episode_append(self, agent_id: str, episode: "Episode") -> None:
        self._episodes.setdefault(agent_id, []).append(episode)

    async def episode_query(
        self, agent_id: str, days: int = 1, tags: list[str] | None = None, limit: int = 50,
    ) -> list["Episode"]:
        return self._episodes.get(agent_id, [])[-limit:]

    # L3: semantic memory

    async def semantic_read(self, agent_id: str, topic: str = "index") -> str:
        return self._semantic.get(agent_id, {}).get(topic, "")

    async def semantic_write(self, agent_id: str, topic: str, content: str) -> None:
        self._semantic.setdefault(agent_id, {})[topic] = content

    async def semantic_list(self, agent_id: str) -> list[str]:
        return list(self._semantic.get(agent_id, {}).keys())

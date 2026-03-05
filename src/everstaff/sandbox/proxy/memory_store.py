"""ProxyMemoryStore — forwards MemoryStore calls over IPC channel."""
from __future__ import annotations

from typing import Any, TYPE_CHECKING

from everstaff.protocols import Message, Episode, WorkingState

if TYPE_CHECKING:
    from everstaff.sandbox.ipc.channel import IpcChannel


class ProxyMemoryStore:
    """MemoryStore that forwards all operations over IPC to orchestrator."""

    def __init__(self, channel: "IpcChannel") -> None:
        self._channel = channel

    async def load(self, session_id: str) -> list[Message]:
        result = await self._channel.send_request("memory.load", {
            "session_id": session_id,
        })
        return [
            Message(
                role=m.get("role", "user"),
                content=m.get("content"),
                tool_calls=m.get("tool_calls"),
                tool_call_id=m.get("tool_call_id"),
                name=m.get("name"),
                thinking=m.get("thinking"),
            )
            for m in result.get("messages", [])
        ]

    async def save(
        self,
        session_id: str,
        messages: list[Message],
        *,
        agent_name: str | None = None,
        agent_uuid: str | None = None,
        parent_session_id: str | None = None,
        stats: Any | None = None,
        status: str | None = None,
        system_prompt: str | None = None,
        title: str | None = None,
        max_tokens: int | None = None,
        initiated_by: str | None = None,
        trigger: Any | None = None,
        hitl_requests: list[dict] | None = None,
        extra_permissions: list[str] | None = None,
    ) -> None:
        params: dict[str, Any] = {
            "session_id": session_id,
            "messages": [m.to_dict() for m in messages],
        }
        for key, val in [
            ("agent_name", agent_name), ("agent_uuid", agent_uuid),
            ("parent_session_id", parent_session_id),
            ("status", status), ("system_prompt", system_prompt),
            ("title", title), ("max_tokens", max_tokens),
            ("initiated_by", initiated_by),
            ("hitl_requests", hitl_requests),
            ("extra_permissions", extra_permissions),
        ]:
            if val is not None:
                params[key] = val
        if stats is not None:
            import dataclasses
            params["stats"] = dataclasses.asdict(stats) if dataclasses.is_dataclass(stats) else stats
        if trigger is not None:
            import dataclasses
            params["trigger"] = dataclasses.asdict(trigger) if dataclasses.is_dataclass(trigger) else trigger
        await self._channel.send_request("memory.save", params)

    async def load_stats(self, session_id: str) -> Any:
        result = await self._channel.send_request("memory.load_stats", {
            "session_id": session_id,
        })
        return result.get("stats")

    async def save_workflow(self, session_id: str, record: Any) -> None:
        await self._channel.send_request("memory.save_workflow", {
            "session_id": session_id,
            "record": record,
        })

    async def load_workflows(self, session_id: str) -> list:
        result = await self._channel.send_request("memory.load_workflows", {
            "session_id": session_id,
        })
        return result.get("workflows", [])

    # L1: working memory
    async def working_load(self, agent_id: str) -> WorkingState:
        result = await self._channel.send_request("memory.working_load", {"agent_id": agent_id})
        return WorkingState(**result)

    async def working_save(self, agent_id: str, state: WorkingState) -> None:
        import dataclasses
        await self._channel.send_request("memory.working_save", {
            "agent_id": agent_id,
            "state": dataclasses.asdict(state),
        })

    # L2: episodic memory
    async def episode_append(self, agent_id: str, episode: Episode) -> None:
        import dataclasses
        await self._channel.send_request("memory.episode_append", {
            "agent_id": agent_id,
            "episode": dataclasses.asdict(episode),
        })

    async def episode_query(self, agent_id: str, days: int = 1, tags: list[str] | None = None, limit: int = 50) -> list[Episode]:
        result = await self._channel.send_request("memory.episode_query", {
            "agent_id": agent_id, "days": days, "tags": tags or [], "limit": limit,
        })
        return [Episode(**e) for e in result.get("episodes", [])]

    # L3: semantic memory
    async def semantic_read(self, agent_id: str, topic: str = "index") -> str:
        result = await self._channel.send_request("memory.semantic_read", {
            "agent_id": agent_id, "topic": topic,
        })
        return result.get("content", "")

    async def semantic_write(self, agent_id: str, topic: str, content: str) -> None:
        await self._channel.send_request("memory.semantic_write", {
            "agent_id": agent_id, "topic": topic, "content": content,
        })

    async def semantic_list(self, agent_id: str) -> list[str]:
        result = await self._channel.send_request("memory.semantic_list", {
            "agent_id": agent_id,
        })
        return result.get("topics", [])

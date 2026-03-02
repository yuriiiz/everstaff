from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, TYPE_CHECKING

from everstaff.protocols import Message

if TYPE_CHECKING:
    from everstaff.schema.token_stats import SessionStats
    from everstaff.protocols import AgentEvent, Episode, HitlRequest, FileStore, WorkingState

logger = logging.getLogger(__name__)


class FileMemoryStore:
    def __init__(
        self,
        store_or_dir: "FileStore | str | Path | None" = None,
        *,
        base_dir: "str | Path | None" = None,  # legacy alias
        memory_store: "FileStore | None" = None,
    ) -> None:
        if base_dir is not None and store_or_dir is None:
            store_or_dir = base_dir
        if store_or_dir is None:
            raise TypeError("FileMemoryStore requires a store or directory argument")
        if isinstance(store_or_dir, (str, Path)):
            from everstaff.storage.local import LocalFileStore
            self._session_store: "FileStore" = LocalFileStore(store_or_dir)
        else:
            self._session_store = store_or_dir

        # Keep backward compat alias
        self._store = self._session_store

        # Memory store (optional, for L1/L2/L3)
        self._memory_store: "FileStore | None" = memory_store

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _require_memory_store(self) -> "FileStore":
        if not self._memory_store:
            raise NotImplementedError("No memory_store configured")
        return self._memory_store

    # ------------------------------------------------------------------
    # L0: Session messages (unchanged, uses _session_store)
    # ------------------------------------------------------------------

    def _session_path(self, session_id: str) -> str:
        return f"{session_id}/session.json"

    async def load_stats(self, session_id: str) -> "SessionStats | None":
        """Load previously-saved SessionStats from the session file, or return None."""
        from everstaff.schema.token_stats import SessionStats, TokenUsage
        path = self._session_path(session_id)
        if not await self._session_store.exists(path):
            return None
        try:
            raw = json.loads((await self._session_store.read(path)).decode())
            if not isinstance(raw, dict):
                return None
            meta = raw.get("metadata", {})
            own_calls_data = meta.get("own_calls", [])
            children_calls_data = meta.get("children_calls", [])
            tool_calls_count = meta.get("tool_calls_count", 0)
            errors_count = meta.get("errors_count", 0)
            stats = SessionStats(
                tool_calls_count=tool_calls_count,
                errors_count=errors_count,
            )
            for entry in own_calls_data:
                stats.own_calls.append(TokenUsage(**entry))
            for entry in children_calls_data:
                stats.children_calls.append(TokenUsage(**entry))
            return stats
        except Exception as e:
            logger.warning("FileMemoryStore: could not load stats for %s: %s", session_id, e)
            return None

    async def load(self, session_id: str) -> list[Message]:
        path = self._session_path(session_id)
        if not await self._session_store.exists(path):
            return []
        raw = json.loads((await self._session_store.read(path)).decode())
        # Support both new format (dict with "messages" key) and legacy list format
        data: list[dict[str, Any]] = raw["messages"] if isinstance(raw, dict) else raw
        return [
            Message(
                role=m["role"],
                content=m.get("content"),
                tool_calls=m.get("tool_calls"),
                tool_call_id=m.get("tool_call_id"),
                name=m.get("name"),
                thinking=m.get("thinking"),
            )
            for m in data
        ]

    async def save(
        self,
        session_id: str,
        messages: list[Message],
        *,
        agent_name: str | None = None,
        agent_uuid: str | None = None,
        parent_session_id: str | None = None,
        stats: "SessionStats | None" = None,
        status: str | None = None,
        system_prompt: str | None = None,
        title: str | None = None,
        max_tokens: int | None = None,
        initiated_by: str | None = None,
        trigger: "AgentEvent | None" = None,
        hitl_requests: list[dict] | None = None,
        extra_permissions: list[str] | None = None,
    ) -> None:
        path = self._session_path(session_id)
        existing_meta: dict[str, Any] = {}
        if await self._session_store.exists(path):
            try:
                raw = json.loads((await self._session_store.read(path)).decode())
                if isinstance(raw, dict):
                    existing_meta = {k: v for k, v in raw.items() if k != "messages"}
            except Exception as e:
                logger.warning("FileMemoryStore: could not read existing metadata for %s: %s", session_id, e)

        default_title = existing_meta.get("agent_name") or agent_name or session_id
        existing_metadata = existing_meta.get("metadata", {})
        # max_tokens: use new value if provided, else preserve existing
        resolved_max_tokens = max_tokens if max_tokens is not None else existing_metadata.get("max_tokens")
        # Resolve trigger metadata: use new value if provided, else preserve existing
        resolved_initiated_by = initiated_by if initiated_by is not None else existing_metadata.get("initiated_by")
        import dataclasses
        # Backward compat: old files may have trigger_source/type/event_id flat fields
        existing_trigger = existing_metadata.get("trigger")
        if existing_trigger is None:
            src = existing_metadata.get("trigger_source")
            typ = existing_metadata.get("trigger_type")
            eid = existing_metadata.get("trigger_event_id")
            if src or typ:
                existing_trigger = {"id": eid or "", "source": src or "",
                                    "type": typ or "", "payload": {},
                                    "target_agent": None, "timestamp": ""}
        resolved_trigger = (
            dataclasses.asdict(trigger) if trigger is not None else existing_trigger
        )

        if stats is not None:
            metadata = {
                "title": title or existing_metadata.get("title") or default_title,
                "own_calls": [u.model_dump() for u in stats.own_calls],
                "children_calls": [u.model_dump() for u in stats.children_calls],
                "tool_calls_count": stats.tool_calls_count,
                "errors_count": stats.errors_count,
                "system_prompt": system_prompt if system_prompt is not None
                                 else existing_metadata.get("system_prompt"),
                "max_tokens": resolved_max_tokens,
                "initiated_by": resolved_initiated_by,
                "trigger": resolved_trigger,
            }
        else:
            metadata = {
                "title": title or existing_metadata.get("title") or default_title,
                "own_calls": existing_metadata.get("own_calls", []),
                "children_calls": existing_metadata.get("children_calls", []),
                "tool_calls_count": existing_metadata.get("tool_calls_count", 0),
                "errors_count": existing_metadata.get("errors_count", 0),
                "system_prompt": system_prompt if system_prompt is not None
                                 else existing_metadata.get("system_prompt"),
                "max_tokens": resolved_max_tokens,
                "initiated_by": resolved_initiated_by,
                "trigger": resolved_trigger,
            }

        payload: dict[str, Any] = {
            "session_id": session_id,
            "parent_session_id": existing_meta.get("parent_session_id", parent_session_id),
            "agent_name": existing_meta.get("agent_name", agent_name),
            "agent_uuid": existing_meta.get("agent_uuid", agent_uuid),
            "created_at": existing_meta.get("created_at", datetime.now(timezone.utc).isoformat()),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "status": status or existing_meta.get("status", "running"),
            "metadata": metadata,
            "messages": [m.to_dict() for m in messages],
            "hitl_requests": hitl_requests if hitl_requests is not None else existing_meta.get("hitl_requests", []),
            "extra_permissions": extra_permissions if extra_permissions is not None else existing_meta.get("extra_permissions", []),
        }
        await self._session_store.write(path, json.dumps(payload, ensure_ascii=False, indent=2).encode())

    async def save_workflow(self, session_id: str, record: Any) -> None:
        """Upsert a WorkflowRecord into the session's 'workflows' array."""
        from everstaff.schema.workflow_spec import WorkflowRecord
        path = self._session_path(session_id)
        raw: dict = {}
        if await self._session_store.exists(path):
            raw = json.loads((await self._session_store.read(path)).decode())
        workflows: list[dict] = raw.get("workflows", [])
        plan_id = record.plan_id if hasattr(record, "plan_id") else record.get("plan_id")
        record_dict = record.model_dump(mode="json") if hasattr(record, "model_dump") else record
        for i, wf in enumerate(workflows):
            if wf.get("plan_id") == plan_id:
                workflows[i] = record_dict
                break
        else:
            workflows.append(record_dict)
        raw["workflows"] = workflows
        await self._session_store.write(
            path, json.dumps(raw, ensure_ascii=False, indent=2).encode()
        )

    async def load_workflows(self, session_id: str) -> list:
        """Return all WorkflowRecords stored in this session."""
        from everstaff.schema.workflow_spec import WorkflowRecord
        path = self._session_path(session_id)
        if not await self._session_store.exists(path):
            return []
        raw = json.loads((await self._session_store.read(path)).decode())
        return [WorkflowRecord.model_validate(wf) for wf in raw.get("workflows", [])]

    # ------------------------------------------------------------------
    # L1: Working memory
    # ------------------------------------------------------------------

    async def working_load(self, agent_id: str) -> "WorkingState":
        from everstaff.protocols import WorkingState
        ms = self._require_memory_store()
        path = f"{agent_id}/working.json"
        if not await ms.exists(path):
            return WorkingState()
        raw = json.loads((await ms.read(path)).decode())
        return WorkingState(**raw)

    async def working_save(self, agent_id: str, state: "WorkingState") -> None:
        ms = self._require_memory_store()
        path = f"{agent_id}/working.json"
        await ms.write(path, json.dumps(asdict(state), ensure_ascii=False, indent=2).encode())

    # ------------------------------------------------------------------
    # L2: Episodic memory
    # ------------------------------------------------------------------

    @staticmethod
    def _episode_date(episode: "Episode") -> str:
        """Extract YYYY-MM-DD date string from an episode timestamp."""
        # Try parsing ISO format; fall back to just taking first 10 chars
        try:
            dt = datetime.fromisoformat(episode.timestamp.replace("Z", "+00:00"))
            return dt.strftime("%Y-%m-%d")
        except (ValueError, AttributeError):
            return episode.timestamp[:10]

    async def episode_append(self, agent_id: str, episode: "Episode") -> None:
        ms = self._require_memory_store()
        date_str = self._episode_date(episode)
        path = f"{agent_id}/episodes/{date_str}.jsonl"

        existing = b""
        if await ms.exists(path):
            existing = await ms.read(path)

        line = json.dumps(asdict(episode), ensure_ascii=False)
        if existing and not existing.endswith(b"\n"):
            existing += b"\n"
        new_data = existing + line.encode() + b"\n"
        await ms.write(path, new_data)

    async def episode_query(
        self,
        agent_id: str,
        days: int = 1,
        tags: list[str] | None = None,
        limit: int = 50,
    ) -> list["Episode"]:
        from everstaff.protocols import Episode
        ms = self._require_memory_store()

        today = datetime.now(timezone.utc).date()
        episodes: list[Episode] = []

        for offset in range(days):
            date = today - timedelta(days=offset)
            date_str = date.strftime("%Y-%m-%d")
            path = f"{agent_id}/episodes/{date_str}.jsonl"
            if not await ms.exists(path):
                continue
            raw = (await ms.read(path)).decode()
            for line in raw.strip().splitlines():
                line = line.strip()
                if not line:
                    continue
                ep = Episode(**json.loads(line))
                if tags:
                    if not any(t in ep.tags for t in tags):
                        continue
                episodes.append(ep)
                if len(episodes) >= limit:
                    return episodes

        return episodes

    # ------------------------------------------------------------------
    # L3: Semantic memory
    # ------------------------------------------------------------------

    async def semantic_read(self, agent_id: str, topic: str = "index") -> str:
        ms = self._require_memory_store()
        path = f"{agent_id}/semantic/{topic}.md"
        if not await ms.exists(path):
            return ""
        return (await ms.read(path)).decode()

    async def semantic_write(self, agent_id: str, topic: str, content: str) -> None:
        ms = self._require_memory_store()
        path = f"{agent_id}/semantic/{topic}.md"
        await ms.write(path, content.encode())

    async def semantic_list(self, agent_id: str) -> list[str]:
        ms = self._require_memory_store()
        prefix = f"{agent_id}/semantic"
        files = await ms.list(prefix)
        topics: list[str] = []
        for f in files:
            if f.endswith(".md"):
                # Extract topic name: strip prefix and .md extension
                # files from list() are relative to the store base, e.g.
                # "agent-uuid-1/semantic/patterns.md"
                name = f.rsplit("/", 1)[-1]  # "patterns.md"
                topics.append(name[:-3])  # strip ".md"
        return topics

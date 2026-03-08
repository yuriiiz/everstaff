"""IPC server handler — routes sandbox messages to real implementations."""
from __future__ import annotations

import base64
import logging
from typing import Any, Callable, Awaitable, TYPE_CHECKING

from everstaff.protocols import Message, TraceEvent

if TYPE_CHECKING:
    from everstaff.protocols import FileStore, MemoryStore, TracingBackend
    from everstaff.sandbox.token_store import EphemeralTokenStore
    from everstaff.core.secret_store import SecretStore

logger = logging.getLogger(__name__)


class IpcServerHandler:
    """Routes IPC messages from sandbox to real orchestrator implementations."""

    def __init__(
        self,
        memory_store: "MemoryStore | None" = None,
        tracer: "TracingBackend | None" = None,
        file_store: "FileStore | None" = None,
        token_store: "EphemeralTokenStore | None" = None,
        secret_store: "SecretStore | None" = None,
        on_hitl_detected: Callable[..., Awaitable[None]] | None = None,
        on_stream_event: Callable[[dict], Awaitable[None]] | None = None,
        config_data: dict[str, Any] | None = None,
        mem0_client: Any | None = None,
    ) -> None:
        self._memory = memory_store
        self._tracer = tracer
        self._file_store = file_store
        self._token_store = token_store
        self._secret_store = secret_store
        self._on_hitl_detected = on_hitl_detected
        self._on_stream_event = on_stream_event
        self._config_data = config_data or {}
        self._mem0_client = mem0_client

    async def handle(self, method: str, params: dict[str, Any]) -> Any:
        """Route a single IPC message to the appropriate handler."""
        try:
            if method == "auth":
                return self._handle_auth(params)
            elif method == "memory.save":
                return await self._handle_memory_save(params)
            elif method == "memory.load":
                return await self._handle_memory_load(params)
            elif method == "memory.load_stats":
                return await self._handle_memory_load_stats(params)
            elif method == "memory.save_workflow":
                return await self._handle_memory_save_workflow(params)
            elif method == "memory.load_workflows":
                return await self._handle_memory_load_workflows(params)
            elif method == "tracer.event":
                return self._handle_tracer_event(params)
            elif method == "stream.event":
                return await self._handle_stream_event(params)
            elif method.startswith("mem0."):
                return await self._handle_mem0(method, params)
            elif method.startswith("file."):
                return await self._handle_file_op(method, params)
            elif method.startswith("memory."):
                return await self._handle_memory_extended(method, params)
            else:
                return {"error": f"Unknown method: {method}"}
        except Exception as e:
            logger.exception("IPC handler error method=%s", method)
            return {"error": str(e)}

    def _handle_auth(self, params: dict[str, Any]) -> dict[str, Any]:
        token = params.get("token", "")
        session_id = self._token_store.validate_and_consume(token)
        if session_id is None:
            return {"error": "Invalid or expired token"}
        return {"session_id": session_id, "secrets": self._secret_store.as_dict(), "config": self._config_data}

    async def _handle_memory_save(self, params: dict[str, Any]) -> dict[str, Any]:
        params = dict(params)  # don't mutate caller's dict
        session_id = params.pop("session_id")
        raw_messages = params.pop("messages", [])
        messages = [
            Message(
                role=m.get("role", "user"),
                content=m.get("content"),
                tool_calls=m.get("tool_calls"),
                tool_call_id=m.get("tool_call_id"),
                name=m.get("name"),
                thinking=m.get("thinking"),
                created_at=m.get("created_at"),
            )
            for m in raw_messages
        ]
        # Reconstruct stats if provided
        stats = params.pop("stats", None)
        if stats and isinstance(stats, dict):
            from everstaff.schema.token_stats import SessionStats
            stats = SessionStats(**stats)
        trigger = params.pop("trigger", None)
        if trigger and isinstance(trigger, dict):
            from everstaff.protocols import AgentEvent
            trigger = AgentEvent(**trigger)

        # Detect HITL request for channel broadcast
        status = params.get("status")
        hitl_requests = params.get("hitl_requests")

        # Set path override for sub-sessions so they get saved under root
        root_session_id = params.get("root_session_id")
        if root_session_id and root_session_id != session_id:
            if hasattr(self._memory, "set_session_path"):
                from everstaff.session.index import SessionIndex
                relpath = SessionIndex.session_relpath(session_id, root_session_id)
                self._memory.set_session_path(session_id, relpath)

        await self._memory.save(session_id, messages, stats=stats, trigger=trigger, **params)

        if status == "waiting_for_human" and hitl_requests and self._on_hitl_detected:
            await self._on_hitl_detected(session_id, hitl_requests)

        return {}

    async def _handle_memory_load(self, params: dict[str, Any]) -> dict[str, Any]:
        messages = await self._memory.load(params["session_id"])
        return {"messages": [m.to_dict() for m in messages]}

    async def _handle_memory_load_stats(self, params: dict[str, Any]) -> dict[str, Any]:
        load_stats_fn = getattr(self._memory, "load_stats", None)
        if load_stats_fn:
            stats = await load_stats_fn(params["session_id"])
            if stats:
                import dataclasses
                return {"stats": dataclasses.asdict(stats) if dataclasses.is_dataclass(stats) else stats}
        return {"stats": None}

    async def _handle_memory_save_workflow(self, params: dict[str, Any]) -> dict[str, Any]:
        await self._memory.save_workflow(params["session_id"], params.get("record"))
        return {}

    async def _handle_memory_load_workflows(self, params: dict[str, Any]) -> dict[str, Any]:
        workflows = await self._memory.load_workflows(params["session_id"])
        return {"workflows": workflows}

    def _handle_tracer_event(self, params: dict[str, Any]) -> dict[str, Any]:
        if self._tracer is None:
            return {}
        event = TraceEvent(
            kind=params.get("kind", ""),
            session_id=params.get("session_id", ""),
            parent_session_id=params.get("parent_session_id"),
            timestamp=params.get("timestamp", ""),
            duration_ms=params.get("duration_ms"),
            data=params.get("data", {}),
            trace_id=params.get("trace_id", ""),
            span_id=params.get("span_id", ""),
            parent_span_id=params.get("parent_span_id"),
        )
        self._tracer.on_event(event)
        return {}

    async def _handle_stream_event(self, params: dict[str, Any]) -> dict[str, Any]:
        if self._on_stream_event:
            await self._on_stream_event(params)
        return {}

    async def _handle_file_op(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        op = method.split(".", 1)[1]
        path = params.get("path", "")
        if op == "read":
            data = await self._file_store.read(path)
            return {"data": base64.b64encode(data).decode()}
        elif op == "write":
            raw = base64.b64decode(params.get("data", ""))
            await self._file_store.write(path, raw)
            return {}
        elif op == "exists":
            return {"exists": await self._file_store.exists(path)}
        elif op == "delete":
            await self._file_store.delete(path)
            return {}
        elif op == "list":
            files = await self._file_store.list(params.get("prefix", ""))
            return {"files": files}
        return {"error": f"Unknown file operation: {op}"}

    async def _handle_memory_extended(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Handle L1/L2/L3 memory operations."""
        op = method.split(".", 1)[1]
        if op == "working_load":
            from everstaff.protocols import WorkingState
            state = await self._memory.working_load(params["agent_id"])
            import dataclasses
            return dataclasses.asdict(state)
        elif op == "working_save":
            from everstaff.protocols import WorkingState
            await self._memory.working_save(params["agent_id"], WorkingState(**params["state"]))
            return {}
        elif op == "episode_append":
            from everstaff.protocols import Episode
            await self._memory.episode_append(params["agent_id"], Episode(**params["episode"]))
            return {}
        elif op == "episode_query":
            episodes = await self._memory.episode_query(
                params["agent_id"], params.get("days", 1), params.get("tags"), params.get("limit", 50)
            )
            import dataclasses
            return {"episodes": [dataclasses.asdict(e) for e in episodes]}
        elif op == "semantic_read":
            content = await self._memory.semantic_read(params["agent_id"], params.get("topic", "index"))
            return {"content": content}
        elif op == "semantic_write":
            await self._memory.semantic_write(params["agent_id"], params["topic"], params["content"])
            return {}
        elif op == "semantic_list":
            topics = await self._memory.semantic_list(params["agent_id"])
            return {"topics": topics}
        return {"error": f"Unknown memory operation: {op}"}

    async def _handle_mem0(self, method: str, params: dict[str, Any]) -> Any:
        """Handle mem0.add / mem0.search."""
        op = method.split(".", 1)[1]
        if self._mem0_client is None:
            if op == "search":
                return []
            return {"results": []}
        if op == "add":
            params = dict(params)
            messages = params.pop("messages", [])
            scope = {k: v for k, v in params.items() if v is not None}
            return await self._mem0_client.add(messages, **scope)
        elif op == "search":
            params = dict(params)
            query = params.pop("query", "")
            top_k = params.pop("top_k", None)
            scope = {k: v for k, v in params.items() if v is not None}
            return await self._mem0_client.search(query, top_k=top_k, **scope)
        return {"error": f"Unknown mem0 operation: {op}"}

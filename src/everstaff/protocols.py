# src/protocols.py
"""
Core protocols and data models for the agent framework.
This file has ZERO external dependencies beyond Python stdlib and pydantic.
All other modules depend on this; nothing here depends on anything else.
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable
from uuid import uuid4


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass
class ToolResult:
    tool_call_id: str
    content: str
    is_error: bool = False
    child_stats: Any = None  # SessionStats from a sub-agent, for parent to merge into children_calls

    def as_message(self) -> dict[str, Any]:
        return {
            "role": "tool",
            "tool_call_id": self.tool_call_id,
            "content": self.content,
        }


@dataclass
class Message:
    role: str  # "user" | "assistant" | "tool" | "system"
    content: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    name: str | None = None
    thinking: str | None = None   # stored in history, stripped before LLM

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"role": self.role}
        if self.content is not None:
            d["content"] = self.content
        if self.tool_calls is not None:
            d["tool_calls"] = self.tool_calls
        if self.tool_call_id is not None:
            d["tool_call_id"] = self.tool_call_id
        if self.name is not None:
            d["name"] = self.name
        if self.thinking is not None:
            d["thinking"] = self.thinking
        return d


def _make_trace_id(session_id: str) -> str:
    """Deterministic trace_id from session_id using uuid5."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, session_id)).replace("-", "")


def _make_span_id() -> str:
    """Random 16-char hex span_id (8 bytes)."""
    return os.urandom(8).hex()


@dataclass
class TraceEvent:
    kind: str
    session_id: str
    data: dict[str, Any] = field(default_factory=dict)
    parent_session_id: str | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    duration_ms: float | None = None
    # OTel-compatible span fields
    trace_id: str = field(default="")
    span_id: str = field(default_factory=_make_span_id)
    parent_span_id: str | None = None

    def __post_init__(self) -> None:
        if not self.trace_id:
            self.trace_id = _make_trace_id(self.session_id)


@dataclass
class HookContext:
    session_id: str
    agent_name: str
    metadata: dict[str, Any] = field(default_factory=dict)


class Hook(Protocol):
    """Extension point for business logic in the agent lifecycle."""

    async def on_session_start(self, ctx: "HookContext") -> None: ...
    async def on_session_end(self, ctx: "HookContext", response: str) -> None: ...
    async def on_user_input(self, ctx: "HookContext", content: str) -> str: ...
    async def on_llm_start(self, ctx: "HookContext", messages: list["Message"]) -> list["Message"]: ...
    async def on_llm_end(self, ctx: "HookContext", response: "LLMResponse") -> "LLMResponse": ...
    async def on_tool_start(self, ctx: "HookContext", args: dict, tool_name: str) -> dict: ...
    async def on_tool_end(self, ctx: "HookContext", result: "ToolResult", tool_name: str) -> "ToolResult": ...
    async def on_subagent_start(self, ctx: "HookContext", agent_name: str, prompt: str) -> str: ...
    async def on_subagent_end(self, ctx: "HookContext", agent_name: str, result: str) -> None: ...
    async def on_memory_compact(self, ctx: "HookContext", before: list["Message"], after: list["Message"]) -> None: ...
    async def on_error(self, ctx: "HookContext", error: Exception, phase: str) -> None: ...


class CancellationEvent:
    """Shared cancellation signal for an agent call tree.

    Uses a boolean flag as the primary source of truth (works outside event loop).
    The asyncio.Event is created lazily so it can be awaited inside a running loop.
    """

    def __init__(self) -> None:
        self._cancelled: bool = False
        self._force: bool = False
        self._async_event: asyncio.Event | None = None

    def _get_async_event(self) -> asyncio.Event:
        if self._async_event is None:
            import asyncio
            self._async_event = asyncio.Event()
            if self._cancelled:
                self._async_event.set()
        return self._async_event

    def cancel(self, force: bool = False) -> None:
        self._force = self._force or force  # once forced, stays forced
        self._cancelled = True
        self._get_async_event().set()

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    @property
    def is_force(self) -> bool:
        return self._force


@dataclass
class PermissionResult:
    allowed: bool
    reason: str | None = None
    needs_hitl: bool = False


@dataclass
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    thinking: str | None = None   # Claude extended thinking or o1/o3 reasoning
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def is_final(self) -> bool:
        return not self.tool_calls


@dataclass
class ToolCallRequest:
    id: str
    name: str
    args: dict[str, Any]


@dataclass
class HitlRequest:
    """Describes what the agent needs from a human."""
    hitl_id: str
    type: str           # "approve_reject" | "choose" | "provide_input" | "notify"
    prompt: str
    options: list[str] = field(default_factory=list)
    context: str = ""
    tool_call_id: str = ""  # tool_call_id of the request_human_input call, for proper message reconstruction on resume
    origin_session_id: str = ""     # deepest child session that originated this HITL
    origin_agent_name: str = ""     # agent name of the originator
    timeout_seconds: int = 86400    # default 1 day; 0 = no timeout


@dataclass
class HitlResolution:
    """Human's response to a HITL request."""
    decision: str                    # "approved" | "rejected" | option text | free text
    resolved_at: datetime
    resolved_by: str = "human"
    comment: str | None = None


class HumanApprovalRequired(Exception):
    """Raised to pause a session for human input. Carries one or more requests."""
    def __init__(self, requests: "list[HitlRequest] | HitlRequest") -> None:
        if isinstance(requests, HitlRequest):
            requests = [requests]
        super().__init__(f"HITL required: {len(requests)} request(s)")
        self.requests: list[HitlRequest] = requests


@dataclass
class AgentEvent:
    """Generic event flowing through the EventBus."""
    id: str = field(default_factory=lambda: str(uuid4()))
    source: str = ""
    type: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    target_agent: str | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class Episode:
    """A single execution record summary (L2 episodic memory)."""
    timestamp: str
    trigger: str
    action: str
    result: str
    duration_ms: int = 0
    session_id: str = ""
    tags: list[str] = field(default_factory=list)


@dataclass
class WorkingState:
    """Agent's current working state (L1 working memory)."""
    goals_progress: dict[str, Any] = field(default_factory=dict)
    pending_items: list[str] = field(default_factory=list)
    recent_decisions: list[dict[str, Any]] = field(default_factory=list)
    custom: dict[str, Any] = field(default_factory=dict)


@dataclass
class Decision:
    """Output of the ThinkEngine."""
    action: str  # "execute" | "skip" | "defer"
    reasoning: str
    task_prompt: str = ""
    priority: str = "normal"  # "high" | "normal" | "low"


# ---------------------------------------------------------------------------
# Protocols (structural typing - no inheritance needed)
# ---------------------------------------------------------------------------

@runtime_checkable
class Tool(Protocol):
    @property
    def definition(self) -> ToolDefinition: ...
    async def execute(self, args: dict[str, Any]) -> ToolResult: ...


@runtime_checkable
class ToolRegistry(Protocol):
    def register(self, tool: Tool) -> None: ...
    def get_definitions(self) -> list[ToolDefinition]: ...
    async def execute(self, name: str, args: dict[str, Any], tool_call_id: str) -> ToolResult: ...
    def has_tool(self, name: str) -> bool: ...


@runtime_checkable
class MemoryStore(Protocol):
    # L0: session messages
    async def load(self, session_id: str) -> list[Message]: ...
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
        trigger: "AgentEvent | None" = None,
        hitl_requests: list[dict] | None = None,
    ) -> None: ...

    # Workflow persistence
    async def save_workflow(self, session_id: str, record: Any) -> None: ...
    async def load_workflows(self, session_id: str) -> list[Any]: ...

    # L1: working memory
    async def working_load(self, agent_id: str) -> WorkingState: ...
    async def working_save(self, agent_id: str, state: WorkingState) -> None: ...

    # L2: episodic memory
    async def episode_append(self, agent_id: str, episode: Episode) -> None: ...
    async def episode_query(
        self, agent_id: str, days: int = 1, tags: list[str] | None = None, limit: int = 50,
    ) -> list[Episode]: ...

    # L3: semantic memory
    async def semantic_read(self, agent_id: str, topic: str = "index") -> str: ...
    async def semantic_write(self, agent_id: str, topic: str, content: str) -> None: ...
    async def semantic_list(self, agent_id: str) -> list[str]: ...


@runtime_checkable
class FileStore(Protocol):
    """Abstract file storage backend. Paths are relative strings."""
    async def read(self, path: str) -> bytes: ...
    async def write(self, path: str, data: bytes) -> None: ...
    async def exists(self, path: str) -> bool: ...
    async def delete(self, path: str) -> None: ...
    async def list(self, prefix: str) -> list[str]: ...


@runtime_checkable
class CompressionStrategy(Protocol):
    async def compress(self, messages: list[Message]) -> list[Message]: ...


@runtime_checkable
class TracingBackend(Protocol):
    def on_event(self, event: TraceEvent) -> None: ...


@runtime_checkable
class PermissionChecker(Protocol):
    def check(self, tool_name: str, args: dict[str, Any]) -> PermissionResult: ...


@runtime_checkable
class PromptInjector(Protocol):
    def get_prompt_injection(self) -> str: ...


@runtime_checkable
class McpProvider(PromptInjector, Protocol):
    def get_tools(self) -> list[Tool]: ...
    async def aclose(self) -> None: ...


@runtime_checkable
class SkillProvider(PromptInjector, Protocol):
    def get_tools(self) -> list[Tool]: ...


@runtime_checkable
class KnowledgeProvider(PromptInjector, Protocol):
    def get_tools(self) -> list[Tool]: ...


@runtime_checkable
class SubAgentProvider(PromptInjector, Protocol):
    def get_tools(self) -> list[Tool]: ...


@runtime_checkable
class LLMClient(Protocol):
    async def complete(
        self,
        messages: list[Message],
        tools: list[ToolDefinition],
        system: str | None = None,
    ) -> LLMResponse: ...


@runtime_checkable
class HitlChannel(Protocol):
    """Bidirectional HITL channel — push requests to users, receive resolutions."""

    async def send_request(self, session_id: str, request: "HitlRequest") -> None:
        """Push a HITL request to the user via this channel."""
        ...

    async def on_resolved(self, hitl_id: str, resolution: "HitlResolution") -> None:
        """Called when ANY channel resolves this HITL request. Handle cleanup."""
        ...

    async def start(self) -> None:
        """Start the channel listener (webhook server, ws listener, etc.)."""
        ...

    async def stop(self) -> None:
        """Stop the channel listener."""
        ...

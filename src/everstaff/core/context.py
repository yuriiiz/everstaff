from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from pathlib import Path
    from everstaff.builder.environment import RuntimeEnvironment

from everstaff.tools.pipeline import ToolCallPipeline
from everstaff.nulls import (
    AllowAllChecker, NullKnowledgeProvider,
    NullMcpProvider,
    NullSkillProvider, NullSubAgentProvider, NullTracer,
)
from everstaff.protocols import (
    AgentEvent, CancellationEvent, FileStore, Hook, KnowledgeProvider, McpProvider,
    MemoryStore, PermissionChecker, PromptInjector,
    SkillProvider, SubAgentProvider, ToolRegistry, TracingBackend,
)


@dataclass
class AgentContext:
    # Required
    tool_registry: ToolRegistry
    memory: MemoryStore
    tool_pipeline: ToolCallPipeline

    # Optional (NullObject defaults)
    permissions: PermissionChecker = field(default_factory=AllowAllChecker)
    skill_provider: SkillProvider = field(default_factory=NullSkillProvider)
    knowledge_provider: KnowledgeProvider = field(default_factory=NullKnowledgeProvider)
    sub_agent_provider: SubAgentProvider = field(default_factory=NullSubAgentProvider)
    mcp_provider: McpProvider = field(default_factory=NullMcpProvider)

    # Metadata & infrastructure
    agent_name: str = ""
    agent_uuid: str = ""
    system_prompt: str | None = None
    session_id: str = field(default_factory=lambda: str(uuid4()))
    parent_session_id: str | None = None
    root_session_id: str | None = None  # root of the session tree; == session_id for roots
    hooks: list[Hook] = field(default_factory=list)
    tracer: TracingBackend = field(default_factory=NullTracer)
    cancellation: CancellationEvent = field(default_factory=CancellationEvent)
    caller_span_id: str | None = None  # parent's span_id when this session was spawned

    max_tokens: int | None = None     # output token limit forwarded to LLM; stored in session metadata
    trigger: AgentEvent | None = None  # Event that initiated this session

    sessions_dir: str | None = None   # base dir for dynamic agent/skill storage
    file_store: FileStore | None = None  # FileStore for stateless cancellation signals
    workdir: "Path | None" = None  # workspace directory for file change tracking
    channel_manager: Any = None          # ChannelManager for HITL broadcast (set by API/CLI layer)
    extra_providers: list[PromptInjector] = field(default_factory=list)  # extensible prompt injectors (e.g. Mem0)
    _env: "RuntimeEnvironment | None" = field(default=None, repr=False)  # set by AgentBuilder after build()

    async def aclose(self) -> None:
        """Release all held resources. Safe to call multiple times."""
        try:
            await self.mcp_provider.aclose()
        except Exception:
            pass

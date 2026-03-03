"""Agent specification models parsed from YAML definitions."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from everstaff.permissions import PermissionConfig
from everstaff.schema.autonomy import AutonomyConfig, HitlChannelRef


class MCPServerSpec(BaseModel):
    """An MCP server the agent should connect to."""

    name: str
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    transport: Literal["stdio", "sse", "streamable_http"] = "stdio"
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    icon: str | None = None

    @model_validator(mode="after")
    def validate_transport_fields(self):
        if self.transport == "stdio" and not self.command:
            raise ValueError("stdio transport requires 'command'")
        if self.transport in ("sse", "streamable_http") and not self.url:
            raise ValueError(f"{self.transport} transport requires 'url'")
        return self


class SubAgentSpec(BaseModel):
    """A sub-agent that the parent agent can delegate tasks to."""

    name: str = ""  # Logical name used as tool identifier
    ref_uuid: str | None = None
    description: str = ""  # May be filled from referenced agent YAML
    instructions: str = ""  # May be filled from referenced agent YAML
    adviced_model_kind: str = "inherit"
    tools: list[str] | None = None
    skills: list[str] = Field(default_factory=list)
    knowledge_base: list[KnowledgeSourceSpec] = Field(default_factory=list)
    mcp_servers: list[MCPServerSpec] = Field(default_factory=list)
    max_turns: int = 20

    def to_agent_spec(self) -> AgentSpec:
        """Convert this SubAgentSpec to a minimal AgentSpec for building a child runtime."""
        return AgentSpec(
            agent_name=self.name or "sub-agent",
            instructions=self.instructions,
            description=self.description,
            tools=self.tools or [],
            skills=self.skills,
            adviced_model_kind=self.adviced_model_kind,
        )


class KnowledgeSourceSpec(BaseModel):
    """A knowledge source configuration."""

    type: str  # "local_dir", future: "vector_db", "web", etc.
    path: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class AgentSpec(BaseModel):
    """Full agent specification parsed from a YAML file."""

    uuid: str | None = None
    agent_name: str
    source: str = "custom"  # "builtin", "custom", "onetime"
    description: str = ""
    version: str = "0.1.0"
    adviced_model_kind: str = "smart"
    instructions: str = ""
    tools: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    knowledge_base: list[KnowledgeSourceSpec] = Field(default_factory=list)
    mcp_servers: list[MCPServerSpec] = Field(default_factory=list)
    sub_agents: dict[str, SubAgentSpec] = Field(default_factory=dict)

    # Permissions
    permissions: PermissionConfig = Field(default_factory=PermissionConfig)

    # Autonomy
    autonomy: AutonomyConfig = Field(default_factory=AutonomyConfig)

    model_override: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    enable_bootstrap: bool = False

    # HITL — controls when the request_human_input tool is registered
    # "always"     = supervised: agent must get approval before every action
    # "on_request" = full HITL (blocking + notify), agent decides when to ask
    # "notify"     = notify-only (non-blocking, fire-and-forget)
    # "never"      = tool not registered
    hitl_mode: Literal["always", "on_request", "notify", "never"] = "on_request"
    hitl_channels: list[HitlChannelRef] = Field(default_factory=list)

    # Workflow — when set, the agent operates in workflow/coordinator mode.
    workflow: WorkflowSpec | None = None


# Resolve the forward reference to WorkflowSpec now that both modules are available.
from everstaff.schema.workflow_spec import WorkflowSpec  # noqa: E402
AgentSpec.model_rebuild()
SubAgentSpec.model_rebuild()

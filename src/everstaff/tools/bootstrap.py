"""Bootstrap tools: create_agent for dynamic agent creation."""
from __future__ import annotations

import logging
import yaml
from pathlib import Path
from typing import TYPE_CHECKING, Any

from everstaff.protocols import ToolDefinition, ToolResult

if TYPE_CHECKING:
    from everstaff.core.context import AgentContext
    from everstaff.protocols import LLMClient

logger = logging.getLogger(__name__)

_GENERATE_AGENT_PROMPT = """Generate a YAML AgentSpec for a {domain} expert agent named "{name}".

Available tools: {tools}
Available skills: {skills}

Output ONLY valid YAML with these fields:
name: {name}
description: <one sentence describing what this agent does>
instructions: <detailed system instructions for this expert>
adviced_model_kind: smart
tools: <list of tool names from available tools, or []>
skills: <list of skill names from available skills, or []>

Do not include create_agent or create_skill in tools."""


class CreateAgentTool:
    """Dynamically generates a domain-expert sub-agent and registers it for immediate use."""

    def __init__(self, ctx: "AgentContext", llm: "LLMClient") -> None:
        self._ctx = ctx
        self._llm = llm

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="create_agent",
            description="Dynamically generate a domain-expert sub-agent for the current session.",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Snake_case agent name (e.g. sql_expert)"},
                    "domain": {"type": "string", "description": "Domain description (e.g. 'SQL query optimization')"},
                    "tools": {"type": "array", "items": {"type": "string"}, "description": "Tool names to give the agent", "default": []},
                    "skills": {"type": "array", "items": {"type": "string"}, "description": "Skill names to give the agent", "default": []},
                },
                "required": ["name", "domain"],
            },
        )

    # Required by DefaultToolRegistry.register_native()
    @property
    def name(self) -> str:
        return "create_agent"

    def _agent_yaml_path(self, name: str) -> Path:
        sessions_dir = self._ctx.sessions_dir or ".agent/sessions"
        return Path(sessions_dir) / self._ctx.session_id / "agents" / f"{name}.yaml"

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        name = args["name"]
        domain = args.get("domain", "")
        tools = args.get("tools", [])
        skills = args.get("skills", [])

        yaml_path = self._agent_yaml_path(name)

        # Cache hit: return immediately without calling LLM
        if yaml_path.exists():
            logger.debug("create_agent: cache hit for %s", name)
            return ToolResult(tool_call_id="", content=name)

        # Generate YAML via LLM
        try:
            from everstaff.protocols import Message
            prompt = _GENERATE_AGENT_PROMPT.format(
                name=name, domain=domain,
                tools=tools or "none", skills=skills or "none",
            )
            response = await self._llm.complete(
                messages=[Message(role="user", content=prompt)],
                tools=[],
                system=None,
            )
            raw_yaml = (response.content or "").strip()
            # Strip markdown code fences if present
            if raw_yaml.startswith("```"):
                # Skip the opening fence line (```yaml or ```)
                first_newline = raw_yaml.index("\n")
                body = raw_yaml[first_newline + 1:]
                # Find the closing fence and stop there
                end = body.find("\n```")
                if end != -1:
                    raw_yaml = body[:end]
                else:
                    raw_yaml = body

            spec_data = yaml.safe_load(raw_yaml)
            if not isinstance(spec_data, dict) or "name" not in spec_data:
                return ToolResult(tool_call_id="", content=f"Invalid agent spec generated for {name}", is_error=True)

        except Exception as e:
            logger.warning("create_agent: LLM generation failed for %s: %s", name, e)
            return ToolResult(tool_call_id="", content=f"Failed to generate agent {name}: {e}", is_error=True)

        # Write YAML to session-scoped cache
        yaml_path.parent.mkdir(parents=True, exist_ok=True)
        yaml_path.write_text(raw_yaml)

        # Register into SubAgentProvider and ToolRegistry (best-effort)
        try:
            self._register_agent(name, spec_data)
        except Exception as e:
            logger.warning("create_agent: registration failed for %s: %s", name, e)

        return ToolResult(tool_call_id="", content=name)

    def _register_agent(self, name: str, spec_data: dict) -> None:
        from everstaff.schema.agent_spec import SubAgentSpec

        sub_spec = SubAgentSpec(
            name=name,
            description=spec_data.get("description", f"{name} expert"),
            instructions=spec_data.get("instructions", ""),
            adviced_model_kind=spec_data.get("adviced_model_kind", "smart"),
            tools=spec_data.get("tools", []),
            skills=spec_data.get("skills", []),
        )

        env = self._ctx._env
        if env is None:
            logger.warning(
                "create_agent: AgentContext has no _env reference — "
                "agent '%s' written to YAML cache but not registered in-process",
                name,
            )
            return

        provider = self._ctx.sub_agent_provider
        if hasattr(provider, "register"):
            provider.register(name, sub_spec)
        # DelegateTaskTool is already in the ToolRegistry — no need to register separately

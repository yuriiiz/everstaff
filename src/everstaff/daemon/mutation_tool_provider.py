"""MutationToolProvider — provides self-mutation tools for daemon agents.

These tools are injected into the agent's runtime during act phase.
Each tool triggers HITL approval before applying changes.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from everstaff.protocols import ToolDefinition

logger = logging.getLogger(__name__)

_MUTATION_FIELDS = {
    "update_agent_skills": ("skills", "Add, remove, or modify the agent's skills list"),
    "update_agent_mcp": ("mcp_servers", "Add or remove MCP server configurations"),
    "update_agent_instructions": ("instructions", "Modify the agent's system instructions"),
    "update_agent_triggers": ("autonomy.triggers", "Add or modify autonomy triggers"),
}


class MutationToolProvider:
    def __init__(
        self,
        agent_name: str,
        agent_yaml_path: str | Path,
        daemon_reload_fn: Callable,
    ) -> None:
        self._agent_name = agent_name
        self._yaml_path = Path(agent_yaml_path)
        self._reload_fn = daemon_reload_fn

    def get_tools(self) -> list[ToolDefinition]:
        tools = []
        for tool_name, (field, description) in _MUTATION_FIELDS.items():
            tools.append(ToolDefinition(
                name=tool_name,
                description=f"{description}. Requires HITL approval. Cannot modify permissions.",
                parameters={
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["add", "remove", "replace"],
                        },
                        "value": {
                            "description": f"The new value for {field}",
                        },
                        "reasoning": {
                            "type": "string",
                            "description": "Why this change is needed",
                        },
                    },
                    "required": ["action", "value", "reasoning"],
                },
            ))
        return tools

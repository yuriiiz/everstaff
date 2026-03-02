"""AgentDefinitionWriter implementations for persisting permanent permission grants."""
from __future__ import annotations

import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


class YamlAgentDefinitionWriter:
    """Write permission grants back to agent YAML files."""

    def __init__(self, agents_dir: str) -> None:
        self._agents_dir = Path(agents_dir)

    async def add_allow_permission(self, agent_name: str, pattern: str) -> None:
        path = self._agents_dir / f"{agent_name}.yaml"
        if not path.exists():
            logger.warning("Agent YAML not found: %s", path)
            return

        data = yaml.safe_load(path.read_text()) or {}
        permissions = data.setdefault("permissions", {})
        allow = permissions.setdefault("allow", [])

        if pattern not in allow:
            allow.append(pattern)
            path.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True))
            logger.info("Permanently granted '%s' to agent '%s'", pattern, agent_name)

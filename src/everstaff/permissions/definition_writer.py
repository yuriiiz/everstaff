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

    async def add_allow_permission(
        self,
        agent_identifier: str,
        pattern: str,
        *,
        agent_path: str | Path | None = None,
    ) -> None:
        """Add an allow permission to an agent's YAML file.

        agent_identifier can be a UUID (tries {uuid}.yaml first) or agent_name.
        If agent_path is provided, use it directly (skips search).
        """
        if agent_path:
            path = Path(agent_path)
        else:
            # Try UUID-based path first
            path = self._agents_dir / f"{agent_identifier}.yaml"
        if not path.exists():
            # Fall back to scanning by agent_name or uuid inside YAML
            path = None
            if self._agents_dir.exists():
                for f in self._agents_dir.glob("*.yaml"):
                    try:
                        data = yaml.safe_load(f.read_text()) or {}
                        if data.get("uuid") == agent_identifier or data.get("agent_name") == agent_identifier:
                            path = f
                            break
                    except Exception:
                        pass
            if not path:
                logger.warning("Agent YAML not found for: %s", agent_identifier)
                return

        data = yaml.safe_load(path.read_text()) or {}
        permissions = data.setdefault("permissions", {})
        allow = permissions.setdefault("allow", [])

        if pattern not in allow:
            allow.append(pattern)
            path.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True))
            logger.info("Permanently granted '%s' to agent '%s'", pattern, agent_identifier)

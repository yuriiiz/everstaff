"""Load sub-agent definitions from YAML and filesystem."""

from __future__ import annotations

import logging
from pathlib import Path

from everstaff.schema.agent_spec import SubAgentSpec
from everstaff.utils.yaml_loader import parse_yaml_frontmatter, load_yaml

logger = logging.getLogger(__name__)


def load_sub_agents_from_filesystem(agents_dir: str | Path) -> dict[str, SubAgentSpec]:
    """Load sub-agent definitions from .agents/ directory.

    Each agent is a markdown file with YAML frontmatter containing:
    - name (used as agent key)
    - description
    And markdown body used as instructions.
    """
    agents_dir = Path(agents_dir).expanduser().resolve()
    if not agents_dir.exists():
        return {}

    agents: dict[str, SubAgentSpec] = {}

    for yaml_file in sorted(agents_dir.glob("*.yaml")):
        try:
            yaml_data = load_yaml(yaml_file)
            uuid = yaml_data.get("uuid", "")
            name = yaml_data.get("name", yaml_file.stem)
            description = yaml_data.get("description", "")
            instructions = yaml_data.get("instructions", "")
            model_kind = yaml_data.get("adviced_model_kind", "inherit")
            tools = yaml_data.get("tools", [])
            skills = yaml_data.get("skills", [])
            knowledge_base = yaml_data.get("knowledge_base", [])
            mcp_servers = yaml_data.get("mcp_servers", [])
            max_turns = yaml_data.get("max_turns", 20)

            agents[name] = SubAgentSpec(
                ref_uuid=uuid,
                description=description,
                instructions=instructions,
                adviced_model_kind=model_kind,
                tools=tools,
                skills=skills,
                knowledge_base=knowledge_base,
                mcp_servers=mcp_servers,
                max_turns=max_turns,
            )
        except Exception:
            raise
            continue

    return agents


def resolve_sub_agent_refs(
    sub_agents: dict[str, SubAgentSpec],
    agents_dir: str | Path,
) -> dict[str, SubAgentSpec]:
    """For any SubAgentSpec with a ref_uuid but missing description/instructions,
    locate the corresponding YAML file in agents_dir and fill the fields from it.
    Entries with no ref_uuid or already-complete specs are left unchanged.
    """
    available_agents = load_sub_agents_from_filesystem(agents_dir)
    uuid_map_agent = {}

    for agent in available_agents.values():
        uuid_map_agent[agent.ref_uuid] = agent

    resolved: dict[str, SubAgentSpec] = {}
    for name, spec in sub_agents.items():
        if spec.ref_uuid:
            ref_data = uuid_map_agent.get(spec.ref_uuid)
            if ref_data:
                # Preserve the dict key as the logical name for the sub-agent.
                # ref_data was loaded without a name so we must set it here.
                resolved[name] = ref_data.model_copy(update={"name": name})
                logger.debug("Resolved sub-agent '%s' from ref_uuid=%s", name, spec.ref_uuid)
            else:
                logger.warning(
                    "Sub-agent '%s' has ref_uuid=%s but no matching agent YAML was found in %s",
                    name, spec.ref_uuid, agents_dir,
                )
                resolved[name] = spec.model_copy(update={"name": name}) if not spec.name else spec
        else:
            # Ensure the dict key is reflected in spec.name for inline specs
            resolved[name] = spec.model_copy(update={"name": name}) if not spec.name else spec

    return resolved

"""Bootstrap tool: create_skill for writing skill packages to install dirs."""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import yaml

from everstaff.protocols import ToolDefinition, ToolResult

logger = logging.getLogger(__name__)


class CreateSkillTool:
    """Creates a new skill by writing SKILL.md (and optional scripts) to all install dirs."""

    def __init__(self, install_dirs: list[str]) -> None:
        self._install_dirs = [Path(d).expanduser().resolve() for d in install_dirs]

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="create_skill",
            description="Create a new skill with SKILL.md and optional script files.",
            parameters={
                "type": "object",
                "properties": {
                    "skill_name": {
                        "type": "string",
                        "description": "Skill name using letters, numbers, and hyphens (e.g. 'ai-news-digest')",
                    },
                    "description": {
                        "type": "string",
                        "description": "When to use this skill — starts with 'Use when...'",
                    },
                    "content": {
                        "type": "string",
                        "description": "Markdown body of SKILL.md (without frontmatter)",
                    },
                    "scripts": {
                        "type": "string",
                        "description": "Optional JSON object mapping filename to content, e.g. '{\"run.py\": \"print(1)\"}'",
                        "default": "",
                    },
                },
                "required": ["skill_name", "description", "content"],
            },
        )

    @property
    def name(self) -> str:
        return "create_skill"

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        skill_name = args["skill_name"]
        description = args["description"]
        content = args["content"]
        scripts_raw = args.get("scripts", "")

        # Validate skill_name to prevent path traversal
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]*", skill_name):
            return ToolResult(
                tool_call_id="",
                content=f"Invalid skill name '{skill_name}': must use only letters, numbers, hyphens, dots, and underscores",
                is_error=True,
            )

        # Check if skill already exists in any install dir
        for d in self._install_dirs:
            try:
                exists = (d / skill_name).exists()
            except PermissionError:
                continue  # can't read dir; will be skipped during write too
            if exists:
                return ToolResult(
                    tool_call_id="",
                    content=f"Skill '{skill_name}' already exists in {d}",
                    is_error=True,
                )

        # Build SKILL.md content with frontmatter (use yaml.dump to prevent injection)
        frontmatter = yaml.dump(
            {"name": skill_name, "description": description},
            default_flow_style=False,
            allow_unicode=True,
        ).strip()
        skill_md = f"---\n{frontmatter}\n---\n\n{content}"

        # Parse optional scripts
        scripts: dict[str, str] = {}
        if scripts_raw:
            try:
                scripts = json.loads(scripts_raw)
            except json.JSONDecodeError as e:
                return ToolResult(
                    tool_call_id="",
                    content=f"Invalid scripts JSON: {e}",
                    is_error=True,
                )

        # Write to all install dirs (skip read-only)
        written: list[str] = []
        for d in self._install_dirs:
            try:
                skill_dir = d / skill_name
                skill_dir.mkdir(parents=True, exist_ok=True)
                (skill_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")

                if scripts:
                    scripts_dir = skill_dir / "scripts"
                    scripts_dir.mkdir(parents=True, exist_ok=True)
                    for fname, fcontent in scripts.items():
                        target = (scripts_dir / fname).resolve()
                        if not str(target).startswith(str(scripts_dir.resolve())):
                            return ToolResult(
                                tool_call_id="",
                                content=f"Invalid script filename '{fname}': path traversal detected",
                                is_error=True,
                            )
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_text(fcontent, encoding="utf-8")

                written.append(str(skill_dir))
            except PermissionError:
                logger.debug("Skipping read-only dir %s for skill creation", d)
            except Exception as exc:
                logger.warning("Failed to create skill '%s' in %s: %s", skill_name, d, exc)

        if not written:
            return ToolResult(
                tool_call_id="",
                content=f"Failed to create skill '{skill_name}': no writable directories",
                is_error=True,
            )

        return ToolResult(
            tool_call_id="",
            content=f"Created skill '{skill_name}' in: {', '.join(written)}",
        )

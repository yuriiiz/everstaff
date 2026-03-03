"""MCP template model and manager — CRUD + first-directory-wins discovery."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class RequiredEnvVar(BaseModel):
    """Describes an environment variable that a template requires."""

    key: str
    label: str = ""
    description: str = ""
    secret: bool = False


class MCPTemplate(BaseModel):
    """An installable MCP server template."""

    name: str
    display_name: str = ""
    description: str = ""
    icon: str = ""
    category: str = "general"
    transport: str = "stdio"
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    required_env: list[RequiredEnvVar] = Field(default_factory=list)

    def to_server_spec(self, env_overrides: dict[str, str] | None = None):
        """Convert to MCPServerSpec with env overrides merged."""
        from everstaff.schema.agent_spec import MCPServerSpec

        merged_env = {**self.env, **(env_overrides or {})}
        return MCPServerSpec(
            name=self.name,
            command=self.command,
            args=self.args,
            env=merged_env,
            transport=self.transport,
            url=self.url,
            headers=self.headers,
        )


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class MCPTemplateManager:
    """Manages MCP templates: discovery, CRUD, with first-directory-wins dedup.

    Parameters
    ----------
    template_dirs:
        Ordered list of directories to scan for ``*.yaml`` template files.
        Earlier directories win when duplicate template names are found.
    user_dir:
        The user-writable directory for create / update / delete operations.
        Must be one of the entries in *template_dirs* (typically the first).
    """

    def __init__(
        self,
        template_dirs: list[str],
        user_dir: str | None = None,
    ) -> None:
        self._dirs: list[Path] = [Path(d).expanduser().resolve() for d in template_dirs]
        self._user_dir: Path | None = Path(user_dir).expanduser().resolve() if user_dir else None
        self._index: dict[str, tuple[MCPTemplate, Path]] | None = None

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def _build_index(self) -> dict[str, tuple[MCPTemplate, Path]]:
        """Scan all dirs, first-dir-wins dedup. Returns {name: (template, path)}."""
        if self._index is not None:
            return self._index
        self._index = {}
        for d in self._dirs:
            if not d.exists():
                continue
            for yaml_path in sorted(d.glob("*.yaml")):
                try:
                    tpl = self._load_yaml(yaml_path)
                except Exception:
                    logger.debug("Skipping malformed template at %s", yaml_path, exc_info=True)
                    continue
                if tpl.name in self._index:
                    logger.debug(
                        "Duplicate template '%s' — %s ignored, keeping %s",
                        tpl.name,
                        yaml_path,
                        self._index[tpl.name][1],
                    )
                    continue
                self._index[tpl.name] = (tpl, yaml_path)
        return self._index

    def list(self) -> list[MCPTemplate]:
        """Return all discovered templates (deduplicated, first-dir-wins)."""
        idx = self._build_index()
        return [tpl for tpl, _path in idx.values()]

    def list_with_source(self) -> list[dict[str, Any]]:
        """Return templates with a ``source`` field indicating 'builtin' vs 'user'."""
        idx = self._build_index()
        results: list[dict[str, Any]] = []
        for tpl, path in idx.values():
            source = self._classify_source(path)
            results.append({"template": tpl, "source": source})
        return results

    def get(self, name: str) -> MCPTemplate:
        """Get a template by name. Raises :class:`FileNotFoundError` if not found."""
        idx = self._build_index()
        entry = idx.get(name)
        if entry is None:
            raise FileNotFoundError(f"MCP template '{name}' not found")
        return entry[0]

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create(self, template: MCPTemplate) -> Path:
        """Create a new template in user_dir. Raises :class:`FileExistsError` if duplicate."""
        if self._user_dir is None:
            raise RuntimeError("No user_dir configured for template creation")
        idx = self._build_index()
        if template.name in idx:
            raise FileExistsError(f"MCP template '{template.name}' already exists")
        self._user_dir.mkdir(parents=True, exist_ok=True)
        path = self._user_dir / f"{template.name}.yaml"
        self._write_yaml(path, template)
        self._invalidate()
        return path

    def update(self, name: str, template: MCPTemplate) -> None:
        """Update an existing template. If builtin, creates a user-dir shadow copy."""
        if self._user_dir is None:
            raise RuntimeError("No user_dir configured for template updates")
        idx = self._build_index()
        entry = idx.get(name)
        if entry is None:
            raise FileNotFoundError(f"MCP template '{name}' not found")
        _tpl, existing_path = entry
        source = self._classify_source(existing_path)
        if source == "user":
            # Update in place
            self._write_yaml(existing_path, template)
        else:
            # Create shadow copy in user_dir
            self._user_dir.mkdir(parents=True, exist_ok=True)
            shadow_path = self._user_dir / f"{name}.yaml"
            self._write_yaml(shadow_path, template)
        self._invalidate()

    def delete(self, name: str) -> None:
        """Delete a user template. Raises :class:`PermissionError` for builtins."""
        idx = self._build_index()
        entry = idx.get(name)
        if entry is None:
            raise FileNotFoundError(f"MCP template '{name}' not found")
        _tpl, path = entry
        source = self._classify_source(path)
        if source != "user":
            raise PermissionError(f"Cannot delete builtin template '{name}'")
        path.unlink()
        self._invalidate()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _classify_source(self, path: Path) -> str:
        """Return 'user' if the file is inside user_dir, else 'builtin'."""
        if self._user_dir and path.resolve().is_relative_to(self._user_dir):
            return "user"
        return "builtin"

    def _invalidate(self) -> None:
        """Clear cached index so next access re-scans."""
        self._index = None

    @staticmethod
    def _load_yaml(path: Path) -> MCPTemplate:
        """Parse a YAML file into an MCPTemplate."""
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            raise ValueError(f"Expected mapping in {path}")
        return MCPTemplate(**data)

    @staticmethod
    def _write_yaml(path: Path, template: MCPTemplate) -> None:
        """Serialize an MCPTemplate to a YAML file."""
        data = template.model_dump(exclude_defaults=True)
        # Always include 'name'
        data["name"] = template.name
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, sort_keys=False, indent=2)

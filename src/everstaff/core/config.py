"""Framework-level configuration loading."""

from __future__ import annotations

import importlib.resources as _pkg_resources
import os
import re as _re
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from everstaff.api.auth.models import AuthConfig
from everstaff.permissions import PermissionConfig
from everstaff.schema.model_config import ModelMapping
from everstaff.utils.yaml_loader import load_yaml


class ContextConfig(BaseModel):
    project_context_dirs: list[str] = Field(default_factory=lambda: [".agent/project"])


class StorageConfig(BaseModel):
    type: str = "local"              # "local" | "s3"
    # S3 fields (only used when type="s3")
    s3_bucket: str = ""
    s3_prefix: str = "sessions"
    s3_region: str = "us-east-1"
    s3_endpoint_url: str | None = None
    s3_access_key: str | None = None
    s3_secret_key: str | None = None


class LarkChannelConfig(BaseModel):
    type: Literal["lark"]
    app_id: str = ""
    app_secret: str = ""
    verification_token: str = ""
    chat_id: str = ""
    bot_name: str = "Agent"
    domain: str = "feishu"


class LarkWsChannelConfig(BaseModel):
    type: Literal["lark_ws"]
    app_id: str = ""
    app_secret: str = ""
    chat_id: str = ""
    bot_name: str = "Agent"
    domain: str = "feishu"


class WebhookChannelConfig(BaseModel):
    type: Literal["webhook"]
    url: str = ""
    headers: dict[str, str] = Field(default_factory=dict)


ChannelConfig = Annotated[
    LarkChannelConfig | LarkWsChannelConfig | WebhookChannelConfig,
    Field(discriminator="type"),
]


class TracerConfig(BaseModel):
    type: str                            # "file" | "console" | "otlp"
    # OTLP fields (only used when type="otlp")
    # otlp_endpoint: str = "http://localhost:4318"
    # otlp_service_name: str = "agent"


class WebConfig(BaseModel):
    enabled: bool = True


class DaemonConfig(BaseModel):
    enabled: bool = False
    watch_interval: int = 10
    graceful_stop_timeout: int = 300
    max_concurrent_loops: int = 10


class FrameworkConfig(BaseModel):
    model_mappings: dict[str, ModelMapping] = Field(default_factory=dict)
    agents_dir: str = Field(default_factory=lambda: "./agents")
    skills_dirs: list[str] = Field(default_factory=lambda: ["./skills", ".agent/skills"])
    tools_dirs: list[str] = Field(default_factory=lambda: ["./tools"])
    context: ContextConfig = Field(default_factory=ContextConfig)

    storage: StorageConfig = Field(default_factory=StorageConfig)
    sessions_dir: str = Field(default_factory=lambda: ".agent/sessions")
    channels: dict[str, ChannelConfig] = Field(default_factory=dict)
    tracers: list[TracerConfig] = Field(
        default_factory=lambda: [TracerConfig(type="file")]
    )
    web: WebConfig = Field(default_factory=WebConfig)
    daemon: DaemonConfig = Field(default_factory=DaemonConfig)
    memory_dir: str = Field(default=".agent/memory")
    permissions: PermissionConfig = Field(default_factory=PermissionConfig)
    auth: AuthConfig | None = None

    def resolve_model(self, kind: str) -> ModelMapping:
        if kind not in self.model_mappings:
            available = list(self.model_mappings.keys())
            raise ValueError(f"Unknown model_kind '{kind}'. Available: {available}")
        return self.model_mappings[kind]

    def has_model_kind(self, kind: str) -> bool:
        return kind in self.model_mappings


def _resolve_env_vars(data: Any) -> Any:
    """Recursively resolve ``${VAR}`` references in string values.

    Raises ``ValueError`` if a referenced variable is not set.
    """
    if isinstance(data, str):
        def _sub(m: _re.Match) -> str:
            name = m.group(1)
            val = os.environ.get(name)
            if val is None:
                raise ValueError(
                    f"Environment variable '{name}' is not set"
                )
            return val
        return _re.sub(r"\$\{([^}]+)\}", _sub, data)
    if isinstance(data, dict):
        return {k: _resolve_env_vars(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_resolve_env_vars(item) for item in data]
    return data


def _apply_env_model_overrides(mappings: dict[str, ModelMapping]) -> dict[str, ModelMapping]:
    """Apply AGENT_MODEL_<KIND>=<litellm_model> env var overrides."""
    prefix = "AGENT_MODEL_"
    for key, value in os.environ.items():
        if key.startswith(prefix):
            kind = key[len(prefix):].lower()
            if kind in mappings:
                mappings[kind].model_id = value
            else:
                mappings[kind] = ModelMapping(model_id=value)
    return mappings


def _builtin_skills_path() -> str:
    """Return the path to the bundled builtin_skills directory."""
    try:
        # When installed as a package
        ref = _pkg_resources.files("everstaff") / "builtin_skills"
        return str(ref)
    except Exception:
        # Fallback for development (skills/ at repo root)
        return str(Path(__file__).parent.parent.parent.parent / "skills")


def _builtin_tools_path() -> str | None:
    """Return the path to the bundled builtin_tools directory, or None if absent."""
    try:
        ref = _pkg_resources.files("everstaff") / "builtin_tools"
        p = str(ref)
        if Path(p).exists():
            return p
    except Exception:
        pass
    return None


def _builtin_agents_path() -> str | None:
    """Return the path to the bundled builtin_agents directory, or None if absent."""
    try:
        ref = _pkg_resources.files("everstaff") / "builtin_agents"
        p = str(ref)
        if Path(p).exists():
            return p
    except Exception:
        pass
    return None


def _user_config_path() -> Path:
    """Return path to .agent/config.yaml in the current working directory."""
    return Path.cwd() / ".agent" / "config.yaml"


def _builtin_defaults() -> FrameworkConfig:
    """Layer 1: built-in defaults with builtin_skills/tools injected."""
    mappings = _apply_env_model_overrides({})
    cfg = FrameworkConfig(model_mappings=mappings)
    # Prepend builtin skills (always available, user dirs take precedence)
    builtin_skills = _builtin_skills_path()
    if builtin_skills not in cfg.skills_dirs:
        cfg = cfg.model_copy(update={"skills_dirs": [builtin_skills] + cfg.skills_dirs})
    # Append builtin tools (user tools_dirs take precedence via last-wins in ToolLoader)
    builtin_tools = _builtin_tools_path()
    if builtin_tools and builtin_tools not in cfg.tools_dirs:
        cfg = cfg.model_copy(update={"tools_dirs": cfg.tools_dirs + [builtin_tools]})
    return cfg


def _merge_user_config(cfg: FrameworkConfig, user_path: Path) -> FrameworkConfig:
    """Layer 2: merge .agent/config.yaml from CWD if it exists."""
    if not user_path.exists():
        return cfg
    data = load_yaml(user_path)
    data = _resolve_env_vars(data)
    # Append-merge list fields, then deduplicate (preserve order, first-wins)
    def _dedup(lst: list[str]) -> list[str]:
        seen: set[str] = set()
        return [x for x in lst if not (x in seen or seen.add(x))]  # type: ignore[func-returns-value]

    new_skills = _dedup(cfg.skills_dirs + data.pop("skills_dirs", []))
    new_tools = _dedup(cfg.tools_dirs + data.pop("tools_dirs", []))
    # Rebuild via model_validate so nested dicts are coerced into Pydantic models
    merged = cfg.model_dump()
    merged.update(data)
    merged["skills_dirs"] = new_skills
    merged["tools_dirs"] = new_tools
    return FrameworkConfig.model_validate(merged)


def _merge_kwargs(
    cfg: FrameworkConfig,
    *,
    skills_dirs: list[str] | None,
    tools_dirs: list[str] | None,
    agents_dir: str | None,
    sessions_dir: str | None,
) -> FrameworkConfig:
    """Layer 3: merge code-level kwargs."""
    updates: dict[str, Any] = {}
    if skills_dirs is not None:
        updates["skills_dirs"] = cfg.skills_dirs + skills_dirs
    if tools_dirs is not None:
        updates["tools_dirs"] = cfg.tools_dirs + tools_dirs
    if agents_dir is not None:
        updates["agents_dir"] = agents_dir
    if sessions_dir is not None:
        updates["sessions_dir"] = sessions_dir
    if not updates:
        return cfg
    return cfg.model_copy(update=updates)


def _load_from_dir(config_dir: Path) -> FrameworkConfig:
    """Load config from a single config.yaml in the given directory."""
    config_path = config_dir / "config.yaml"
    config_data: dict[str, Any] = {}
    if config_path.exists():
        config_data = _resolve_env_vars(load_yaml(config_path))

    raw_mappings = config_data.pop("model_mappings", {})
    parsed = {k: ModelMapping(**v) for k, v in raw_mappings.items()}
    config_data["model_mappings"] = _apply_env_model_overrides(parsed)
    return FrameworkConfig(**config_data)


def load_config(
    config_dir: str | Path | None = None,
    *,
    skills_dirs: list[str] | None = None,
    tools_dirs: list[str] | None = None,
    agents_dir: str | None = None,
    sessions_dir: str | None = None,
) -> FrameworkConfig:
    """Load framework configuration.

    Two paths:
    - config_dir given -> read config.yaml from that directory (full override, no merging)
    - config_dir omitted -> three-layer merge:
        1. built-in defaults (includes builtin_skills path)
        2. .agent/config.yaml in CWD (if exists)
        3. code kwargs (skills_dirs, tools_dirs, agents_dir, sessions_dir)
    """
    if config_dir is not None:
        return _load_from_dir(Path(config_dir).expanduser().resolve())

    cfg = _builtin_defaults()
    cfg = _merge_user_config(cfg, _user_config_path())
    cfg = _merge_kwargs(
        cfg,
        skills_dirs=skills_dirs,
        tools_dirs=tools_dirs,
        agents_dir=agents_dir,
        sessions_dir=sessions_dir,
    )
    return cfg

"""Safe YAML loading with environment variable interpolation."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml


_ENV_VAR_PATTERN = re.compile(r"\$\{(\w+)(?::([^}]*))?\}")


def _interpolate_env_vars(value: str) -> str:
    """Replace ${VAR} or ${VAR:default} patterns with environment variable values."""

    def _replace(match: re.Match) -> str:
        var_name = match.group(1)
        default = match.group(2)
        env_value = os.environ.get(var_name)
        if env_value is not None:
            return env_value
        if default is not None:
            return default
        return match.group(0)  # leave unchanged if no env var and no default

    return _ENV_VAR_PATTERN.sub(_replace, value)


def _walk_and_interpolate(data: Any) -> Any:
    """Recursively walk a data structure and interpolate env vars in strings."""
    if isinstance(data, str):
        return _interpolate_env_vars(data)
    if isinstance(data, dict):
        return {k: _walk_and_interpolate(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_walk_and_interpolate(item) for item in data]
    return data


def load_yaml(path: str | Path) -> dict[str, Any]:
    """Load a YAML file with environment variable interpolation.

    Supports ${VAR} and ${VAR:default} syntax in string values.
    """
    path = Path(path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"YAML file not found: {path}")

    with open(path) as f:
        data = yaml.safe_load(f)

    if data is None:
        return {}

    if not isinstance(data, dict):
        raise ValueError(f"Expected YAML file to contain a mapping, got {type(data).__name__}")

    return _walk_and_interpolate(data)


def parse_yaml_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Parse YAML frontmatter from a markdown file.

    Returns (frontmatter_dict, body_text).
    Frontmatter is delimited by --- on its own lines at the start of the file.
    """
    text = text.strip()
    if not text.startswith("---"):
        return {}, text

    # Find the closing ---
    end_idx = text.find("---", 3)
    if end_idx == -1:
        return {}, text

    frontmatter_str = text[3:end_idx].strip()
    body = text[end_idx + 3:].strip()

    frontmatter = yaml.safe_load(frontmatter_str)
    if frontmatter is None:
        frontmatter = {}

    return frontmatter, body


def save_yaml(path: str | Path, data: dict[str, Any]) -> None:
    """Save a dictionary to a YAML file."""
    path = Path(path).expanduser().resolve()
    with open(path, "w") as f:
        yaml.safe_dump(data, f, sort_keys=False, indent=2)

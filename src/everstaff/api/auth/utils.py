"""Auth utilities — helpers for environment variable expansion and route matching."""

from __future__ import annotations

import os
import re


def expand_env_vars(value: str) -> str:
    """Expand ``${ENV_VAR}`` patterns in *value*.

    Raises ``ValueError`` if a referenced environment variable is not set.
    """

    def _replace(match: re.Match[str]) -> str:
        var_name = match.group(1)
        result = os.environ.get(var_name)
        if result is None:
            raise ValueError(f"Environment variable '{var_name}' is not set")
        return result

    return re.sub(r"\$\{([^}]+)\}", _replace, value)


def matches_route(path: str, patterns: list[str]) -> bool:
    """Check whether *path* matches any pattern in *patterns*.

    Supports:
    - Exact match (e.g. ``/ping``)
    - Trailing ``*`` wildcard (e.g. ``/webhooks/*`` matches ``/webhooks/lark``)
    """
    for pattern in patterns:
        if pattern.endswith("*"):
            prefix = pattern[:-1]  # includes the trailing slash
            if path.startswith(prefix):
                return True
        elif path == pattern:
            return True
    return False

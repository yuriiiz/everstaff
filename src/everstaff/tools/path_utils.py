"""Shared path safety utilities for sandboxed file tools."""
from __future__ import annotations

from pathlib import Path


def resolve_safe_path(workdir: Path, raw: str) -> Path:
    """Resolve ``raw`` relative to ``workdir``.

    Raises ValueError if:
    - raw is an absolute path
    - resolved path escapes workdir after symlink resolution
    """
    if Path(raw).is_absolute():
        raise ValueError(f"Absolute paths not allowed: {raw!r}")

    resolved = (workdir / raw).resolve()

    if not resolved.is_relative_to(workdir.resolve()):
        raise ValueError(f"Path traversal not allowed: {raw!r}")

    return resolved

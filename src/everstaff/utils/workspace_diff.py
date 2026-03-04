"""Workspace snapshot and diff utilities for detecting file changes."""
from __future__ import annotations

import mimetypes
import os
from pathlib import Path

# (size_bytes, mtime_ns)
Snapshot = dict[str, tuple[int, int]]

# Fallback MIME types for extensions the stdlib may not recognise.
_EXTRA_MIME: dict[str, str] = {
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".yaml": "text/yaml",
    ".yml": "text/yaml",
    ".toml": "application/toml",
    ".jsonl": "application/jsonlines",
}


def snapshot_workspace(workdir: Path) -> Snapshot:
    """Return {relative_path: (size, mtime_ns)} for all files under workdir."""
    if not workdir.exists():
        return {}
    result: Snapshot = {}
    root = str(workdir)
    for dirpath, _dirnames, filenames in os.walk(root):
        for fname in filenames:
            full = os.path.join(dirpath, fname)
            rel = os.path.relpath(full, root)
            try:
                st = os.stat(full)
                result[rel] = (st.st_size, st.st_mtime_ns)
            except OSError:
                pass
    return result


def diff_snapshots(before: Snapshot, after: Snapshot) -> tuple[list[str], list[str]]:
    """Compare two snapshots, return (created_paths, modified_paths)."""
    created: list[str] = []
    modified: list[str] = []
    for path, (size, mtime) in after.items():
        if path not in before:
            created.append(path)
        else:
            old_size, old_mtime = before[path]
            if size != old_size or mtime != old_mtime:
                modified.append(path)
    return created, modified


def guess_mime(filename: str) -> str:
    """Guess MIME type from filename, with sensible defaults."""
    mime, _ = mimetypes.guess_type(filename)
    if mime:
        return mime
    ext = os.path.splitext(filename)[1].lower()
    return _EXTRA_MIME.get(ext, "application/octet-stream")

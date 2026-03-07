# Sandbox Workspace Abstraction Design

## Problem

The current codebase assumes local filesystem access for workspace operations:
- `RuntimeEnvironment.working_dir(session_id) -> Path` returns a local path
- Tools (`make_bash_tool(workdir)`, `make_read_tool(workdir)`, etc.) take a `Path`
- `snapshot_workspace(workdir)` / `diff_snapshots()` walk the filesystem directly
- `FileCreatedEvent` emission in `runtime.py` reads file stats from local disk

This works for `ProcessSandbox` and `DockerSandbox` (bind-mount gives host filesystem access), but **breaks for cloud sandboxes** (E2B, Modal, Fly.io) where the workspace lives on a remote machine accessible only through an API.

## Research Findings

### E2B Sandbox
- Uses **FUSE mounts** inside the sandbox for filesystem operations
- Provides `watchDir(path, callback)` API for file change notifications
- REST API for lifecycle, gRPC for real-time file streaming
- File operations: `read()`, `write()`, `list()`, `watch()` — all remote

### Modal / Fly.io
- Modal uses **network filesystem mounts** (`modal.Volume`, `modal.NetworkFileSystem`)
- Workspaces are ephemeral containers with mounted volumes
- File sync is volume-based, not event-based

### Current Codebase Patterns
- Tools use `TOOLS_FACTORY(workdir: Path)` pattern
- `resolve_safe_path(workdir, raw)` enforces path containment
- `snapshot_workspace()` uses `os.walk()` + `os.stat()` (local only)
- `FileCreatedEvent` reads `full.stat().st_size` and `guess_mime()` from disk
- `ProxyFileStore` already abstracts file storage over IPC (read/write/list/exists/delete)

## Design

### Key Insight

There are **two separate concerns** being conflated:

1. **Agent workspace** — where agent tools (bash, read, write, edit, glob) operate. For local/docker sandboxes, tools run inside the sandbox and access the filesystem directly. For cloud sandboxes, tools also run inside the sandbox. **The tools themselves don't need abstraction** — they always see a local filesystem from the sandbox process's perspective.

2. **Workspace observation** — how the **orchestrator** (host) detects file changes made by the agent. This is where the abstraction is needed:
   - Local/Docker: `snapshot_workspace()` / `diff_snapshots()` on the host
   - Cloud: `watchDir()` API or polling remote file listing

### Proposed: `WorkspaceObserver` Protocol

```python
# src/everstaff/sandbox/workspace.py

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator


@dataclass
class FileChange:
    """A detected file change in the workspace."""
    path: str          # relative to workspace root
    kind: str          # "created" | "modified" | "deleted"
    size: int = 0
    mime_type: str = "application/octet-stream"


class WorkspaceObserver(ABC):
    """Observes file changes in an agent's workspace.

    The orchestrator uses this to detect what files the agent created/modified
    during tool execution, for emitting FileCreatedEvent to the frontend.
    """

    @abstractmethod
    async def snapshot(self) -> None:
        """Take a snapshot of current workspace state.

        Called before tool execution to establish a baseline.
        """

    @abstractmethod
    async def diff(self) -> list[FileChange]:
        """Compare current state against last snapshot.

        Called after tool execution to detect changes.
        Returns list of created/modified files since last snapshot().
        """

    @abstractmethod
    async def read_file(self, path: str) -> bytes:
        """Read file content from workspace (for FileCreatedEvent data).

        Path is relative to workspace root.
        """

    async def close(self) -> None:
        """Clean up any resources."""
```

### Implementations

#### `LocalWorkspaceObserver` (ProcessSandbox, DockerSandbox)

```python
class LocalWorkspaceObserver(WorkspaceObserver):
    """Observer for local/bind-mounted workspaces."""

    def __init__(self, workdir: Path) -> None:
        self._workdir = workdir
        self._snapshot: dict[str, tuple[int, int]] = {}

    async def snapshot(self) -> None:
        self._snapshot = snapshot_workspace(self._workdir)

    async def diff(self) -> list[FileChange]:
        after = snapshot_workspace(self._workdir)
        created, modified = diff_snapshots(self._snapshot, after)
        changes = []
        for fp in created:
            full = self._workdir / fp
            changes.append(FileChange(
                path=fp, kind="created",
                size=full.stat().st_size if full.is_file() else 0,
                mime_type=guess_mime(fp),
            ))
        for fp in modified:
            full = self._workdir / fp
            changes.append(FileChange(
                path=fp, kind="modified",
                size=full.stat().st_size if full.is_file() else 0,
                mime_type=guess_mime(fp),
            ))
        return changes

    async def read_file(self, path: str) -> bytes:
        return (self._workdir / path).read_bytes()
```

#### `RemoteWorkspaceObserver` (E2B, cloud sandboxes)

```python
class RemoteWorkspaceObserver(WorkspaceObserver):
    """Observer for remote/cloud workspaces accessed via API."""

    def __init__(self, executor: SandboxExecutor) -> None:
        self._executor = executor
        self._snapshot: dict[str, int] = {}  # path -> size

    async def snapshot(self) -> None:
        # Use sandbox's execute() to list files remotely
        result = await self._executor.execute(SandboxCommand(
            type="bash",
            payload={"command": "find /work -type f -printf '%s %p\\n'", "timeout": 10}
        ))
        self._snapshot = self._parse_file_listing(result.output or "")

    async def diff(self) -> list[FileChange]:
        # Same approach: re-list and compare
        result = await self._executor.execute(SandboxCommand(
            type="bash",
            payload={"command": "find /work -type f -printf '%s %p\\n'", "timeout": 10}
        ))
        after = self._parse_file_listing(result.output or "")
        changes = []
        for path, size in after.items():
            if path not in self._snapshot:
                changes.append(FileChange(path=path, kind="created", size=size))
            elif self._snapshot[path] != size:
                changes.append(FileChange(path=path, kind="modified", size=size))
        return changes

    async def read_file(self, path: str) -> bytes:
        result = await self._executor.execute(SandboxCommand(
            type="bash",
            payload={"command": f"base64 < '{path}'", "timeout": 10}
        ))
        import base64
        return base64.b64decode(result.output or "")
```

#### `IpcWorkspaceObserver` (push-based from sandbox process)

For sandboxes with IPC channels, file changes can be **pushed** from inside the sandbox rather than polled from outside:

```python
class IpcWorkspaceObserver(WorkspaceObserver):
    """Receives file change notifications via IPC from sandbox process."""

    def __init__(self) -> None:
        self._pending_changes: list[FileChange] = []

    def on_file_changed(self, change: FileChange) -> None:
        """Called by IPC handler when sandbox reports a file change."""
        self._pending_changes.append(change)

    async def snapshot(self) -> None:
        self._pending_changes.clear()

    async def diff(self) -> list[FileChange]:
        changes = self._pending_changes[:]
        self._pending_changes.clear()
        return changes

    async def read_file(self, path: str) -> bytes:
        raise NotImplementedError("Use IPC file.read for remote reads")
```

### Integration with SandboxExecutor

```python
class SandboxExecutor(ABC):
    # ... existing methods ...

    def workspace_observer(self) -> WorkspaceObserver | None:
        """Return workspace observer for this executor.

        Returns None if the executor doesn't support workspace observation
        (the runtime will fall back to local snapshot-based detection).
        """
        return None
```

### Integration with Runtime

The change in `runtime.py` is minimal — replace direct `snapshot_workspace()` calls:

```python
# Before (current):
_ws_before = snapshot_workspace(_workdir) if _workdir else {}
# ... tool execution ...
_ws_after = snapshot_workspace(self._ctx.workdir)
_created, _modified = diff_snapshots(_ws_before, _ws_after)

# After (with observer):
observer = self._workspace_observer  # set during init
if observer:
    await observer.snapshot()
# ... tool execution ...
if observer:
    changes = await observer.diff()
    for change in changes:
        yield FileCreatedEvent(
            file_path=change.path,
            file_name=Path(change.path).name,
            size=change.size,
            mime_type=change.mime_type,
        )
```

### What Does NOT Need to Change

- **`working_dir(session_id) -> Path`** — still works. For local/docker, it's a real path. For cloud sandboxes where the orchestrator can't access the filesystem, `working_dir` can return a sentinel path (the orchestrator just passes it to the observer, never reads from it directly).
- **Tool factories** — tools run inside the sandbox, they always see a local filesystem. No change needed.
- **`resolve_safe_path()`** — still works, operates inside sandbox.
- **`ProxyFileStore`** — unrelated; handles session file storage (artifacts), not workspace.

## Migration Plan

1. Add `WorkspaceObserver` protocol and `LocalWorkspaceObserver` implementation
2. Add `workspace_observer()` to `SandboxExecutor` (default returns None)
3. Refactor `runtime.py` to use observer when available, fall back to current behavior
4. `ProcessSandbox` / `DockerSandbox` return `LocalWorkspaceObserver(workdir)`
5. Future cloud backends implement `RemoteWorkspaceObserver` or `IpcWorkspaceObserver`

## Scope

This is a **design-only** document. Implementation will happen when a cloud sandbox backend (E2B, Modal) is actually added. The current `ProcessSandbox` and `DockerSandbox` work fine with the existing snapshot approach — no immediate refactoring needed.

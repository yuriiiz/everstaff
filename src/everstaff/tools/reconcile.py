"""System reconciliation tool for periodic cleanup and archival."""
from __future__ import annotations

import gzip
import logging
import shutil
import tarfile
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from everstaff.protocols import ToolDefinition, ToolResult

if TYPE_CHECKING:
    from everstaff.builder.environment import RuntimeEnvironment

logger = logging.getLogger(__name__)

_DEFAULT_RETENTION_DAYS = 7


class SystemReconcileTool:
    """Framework-level tool for system cleanup: session archival, memory/log/temp cleanup."""

    def __init__(self, env: "RuntimeEnvironment") -> None:
        self._env = env

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="system_reconcile",
            description="Perform system maintenance: archive old sessions, clean memory/logs/temp files.",
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["archive_sessions", "cleanup_memory", "cleanup_logs", "cleanup_temp"],
                        "description": "The cleanup action to perform.",
                    },
                    "retention_days": {
                        "type": "integer",
                        "description": "Keep files newer than this many days (default: 7).",
                        "default": _DEFAULT_RETENTION_DAYS,
                    },
                },
                "required": ["action"],
            },
        )

    @property
    def name(self) -> str:
        return "system_reconcile"

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        action = args["action"]
        retention_days = args.get("retention_days", _DEFAULT_RETENTION_DAYS)
        cutoff = time.time() - (retention_days * 86400)

        dispatch = {
            "archive_sessions": self._archive_sessions,
            "cleanup_memory": self._cleanup_memory,
            "cleanup_logs": self._cleanup_logs,
            "cleanup_temp": self._cleanup_temp,
        }

        handler = dispatch.get(action)
        if handler is None:
            return ToolResult(
                tool_call_id="",
                content=f"Unknown action '{action}'. Valid: {list(dispatch.keys())}",
                is_error=True,
            )

        try:
            result = handler(cutoff, retention_days)
            return ToolResult(tool_call_id="", content=result)
        except Exception as e:
            logger.warning("system_reconcile %s failed: %s", action, e)
            return ToolResult(tool_call_id="", content=f"Error in {action}: {e}", is_error=True)

    def _get_sessions_dir(self) -> Path | None:
        sd = self._env.sessions_dir() if callable(getattr(self._env, "sessions_dir", None)) else None
        return Path(sd) if sd else None

    def _get_project_root(self) -> Path:
        return self._env.project_root() if callable(getattr(self._env, "project_root", None)) else Path.cwd()

    def _archive_sessions(self, cutoff: float, retention_days: int) -> str:
        sessions_dir = self._get_sessions_dir()
        if sessions_dir is None or not sessions_dir.exists():
            return "No sessions directory configured or found."

        archive_dir = sessions_dir.parent / "archive" / "sessions"
        archive_dir.mkdir(parents=True, exist_ok=True)

        archived = []
        for session_path in sorted(sessions_dir.iterdir()):
            if not session_path.is_dir():
                continue
            if session_path.stat().st_mtime > cutoff:
                continue
            # Compress and archive
            archive_name = f"{session_path.name}.tar.gz"
            archive_path = archive_dir / archive_name
            with tarfile.open(archive_path, "w:gz") as tar:
                tar.add(session_path, arcname=session_path.name)
            shutil.rmtree(session_path)
            archived.append(session_path.name)
            logger.info("Archived session '%s' to %s", session_path.name, archive_path)

        if not archived:
            return f"No sessions older than {retention_days} days found."
        return f"Archived {len(archived)} sessions: {', '.join(archived)}"

    def _cleanup_memory(self, cutoff: float, retention_days: int) -> str:
        root = self._get_project_root()
        memory_dir = root / ".agent" / "memory"
        if not memory_dir.exists():
            return "No memory directory found."

        removed = []
        for f in sorted(memory_dir.rglob("*")):
            if not f.is_file():
                continue
            if f.stat().st_mtime > cutoff:
                continue
            f.unlink()
            removed.append(str(f.relative_to(memory_dir)))
            logger.info("Removed memory file: %s", f)

        if not removed:
            return f"No memory files older than {retention_days} days found."
        return f"Cleaned {len(removed)} memory files: {', '.join(removed)}"

    def _cleanup_logs(self, cutoff: float, retention_days: int) -> str:
        root = self._get_project_root()
        log_dirs = [
            root / ".agent" / "logs",
            root / ".agent" / "traces",
        ]

        removed = []
        for log_dir in log_dirs:
            if not log_dir.exists():
                continue
            for f in sorted(log_dir.rglob("*")):
                if not f.is_file():
                    continue
                if f.stat().st_mtime > cutoff:
                    continue
                f.unlink()
                removed.append(str(f.relative_to(root)))
                logger.info("Removed log file: %s", f)

        if not removed:
            return f"No log files older than {retention_days} days found."
        return f"Cleaned {len(removed)} log files: {', '.join(removed)}"

    def _cleanup_temp(self, cutoff: float, retention_days: int) -> str:
        root = self._get_project_root()
        temp_dirs = [
            root / ".agent" / "cache",
            root / ".agent" / "tmp",
        ]

        removed_count = 0
        for temp_dir in temp_dirs:
            if not temp_dir.exists():
                continue
            for f in sorted(temp_dir.rglob("*"), reverse=True):
                if f.stat().st_mtime > cutoff:
                    continue
                if f.is_file():
                    f.unlink()
                    removed_count += 1
                elif f.is_dir() and not any(f.iterdir()):
                    f.rmdir()
                    removed_count += 1

        if removed_count == 0:
            return f"No temp files older than {retention_days} days found."
        return f"Cleaned {removed_count} temp files/directories."

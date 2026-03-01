"""Project context loader — auto-loads CONTEXT.md files into system prompt."""

from __future__ import annotations

from pathlib import Path

from everstaff.utils.yaml_loader import _walk_and_interpolate


class ProjectContextLoader:
    """Loads and merges hierarchical context files (user global -> project -> session)."""

    def __init__(
        self,
        project_context_dirs: list[str] | None = None,
        user_home: str | Path | None = None,
    ) -> None:
        self._project_context_dirs = project_context_dirs or [".project"]
        self._user_home = None
        if user_home:
            self._user_home = Path(user_home).expanduser().resolve()
        self._last_mtimes: dict[str, float] = {}

    def load(
        self,
        project_dir: str | Path | None = None,
    ) -> str:
        """Load and merge context files.

        Merge priority (highest first):
        1. project context files (.agent/CONTEXT.md, etc.)
        2. user global context (~/.project/CONTEXT.md)
        """
        sections: list[str] = []

        # Layer 2: User global context
        if self._user_home:
            user_context = self._load_context_from_dir(self._user_home)
            if user_context:
                sections.append(user_context)

        # Layer 1: Project context
        if project_dir:
            project_path = Path(project_dir).resolve()
            for ctx_dir_name in self._project_context_dirs:
                ctx_dir = project_path / ctx_dir_name
                project_ctx = self._load_context_from_dir(ctx_dir)
                if project_ctx:
                    sections.append(project_ctx)

        if not sections:
            return ""

        merged = "\n\n---\n\n".join(sections)
        # Apply env var interpolation
        return _walk_and_interpolate(merged)

    def has_changes(self) -> bool:
        """Check if any loaded context files have changed since last load."""
        for file_path, mtime in self._last_mtimes.items():
            p = Path(file_path)
            if not p.exists() or p.stat().st_mtime != mtime:
                return True
        return False

    def _load_context_from_dir(self, directory: Path) -> str | None:
        """Load context from a directory — looks for CONTEXT.md and *.context.md files."""
        if not directory.exists():
            return None

        parts: list[str] = []

        # Main CONTEXT.md
        main_ctx = directory / "CONTEXT.md"
        if main_ctx.exists():
            try:
                content = main_ctx.read_text(encoding="utf-8").strip()
                if content:
                    parts.append(content)
                    self._last_mtimes[str(main_ctx)] = main_ctx.stat().st_mtime
            except Exception:
                pass

        # Additional *.context.md files
        for ctx_file in sorted(directory.glob("*.context.md")):
            if ctx_file.name == "CONTEXT.md":
                continue
            try:
                content = ctx_file.read_text(encoding="utf-8").strip()
                if content:
                    parts.append(content)
                    self._last_mtimes[str(ctx_file)] = ctx_file.stat().st_mtime
            except Exception:
                continue

        return "\n\n".join(parts) if parts else None

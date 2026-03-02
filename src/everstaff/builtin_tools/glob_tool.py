"""Glob — find files by pattern."""
from __future__ import annotations

from pathlib import Path

from everstaff.tools.native import tool
from everstaff.tools.path_utils import resolve_safe_path
from everstaff.core.constants import TOOL_MAX_RESULTS as _MAX_RESULTS


def make_glob_tool(workdir: Path):
    """Return a Glob NativeTool scoped to *workdir*."""

    @tool(
        name="Glob",
        description=(
            "Find files matching a glob pattern within the working directory. "
            "All paths must be relative — absolute paths and '..' traversal are not allowed."
        ),
    )
    def glob_search(pattern: str, path: str = ".") -> str:
        """Find files matching a glob pattern within the working directory.

        Args:
            pattern: Glob pattern to match (e.g. '**/*.py', 'src/**/*.ts').
            path: Relative base directory to search in (default: '.'). Must be a relative path and must not use '..' to escape the working directory.
        """
        try:
            base = resolve_safe_path(workdir, path)
        except ValueError as e:
            return f"Error: {e}"

        if not base.exists():
            return f"Error: Directory not found: {path}"
        if not base.is_dir():
            return f"Error: Not a directory: {path}"

        try:
            matches = sorted(base.glob(pattern))
        except Exception as e:
            return f"Error: Invalid glob pattern: {e}"

        # Filter to files only
        files = [m for m in matches if m.is_file()]

        if not files:
            return f"No files matching '{pattern}' in {path}"

        lines = [str(f.relative_to(workdir.resolve())) for f in files[:_MAX_RESULTS]]
        result = "\n".join(lines)

        if len(files) > _MAX_RESULTS:
            result += f"\n\n... ({len(files) - _MAX_RESULTS} more files not shown, total {len(files)})"

        return result

    return glob_search


TOOLS = [make_glob_tool(Path("."))]
TOOLS_FACTORY = make_glob_tool

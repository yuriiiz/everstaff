"""Grep — search file contents by regex."""
from __future__ import annotations

import re
from pathlib import Path

from everstaff.tools.native import tool
from everstaff.tools.path_utils import resolve_safe_path
from everstaff.core.constants import TOOL_MAX_RESULTS as _MAX_RESULTS

_BINARY_CHECK_SIZE = 8192


def _grep_permission_hint(args):
    from everstaff.protocols import PermissionHint
    pat = args.get("pattern", "")
    return PermissionHint("pattern", pat or "*")


def make_grep_tool(workdir: Path):
    """Return a Grep NativeTool scoped to *workdir*."""

    @tool(
        name="Grep",
        description=(
            "Search file contents for a regex pattern. Returns matching lines with file paths and line numbers. "
            "All paths must be relative — absolute paths and '..' traversal are not allowed."
        ),
        permission_hint=_grep_permission_hint,
    )
    def grep_search(pattern: str, path: str = ".", include: str = "") -> str:
        """Search file contents for a regex pattern.

        Args:
            pattern: Regular expression pattern to search for.
            path: Relative directory or file to search in within the working directory (default: '.'). Must not start with '/' or contain '..' segments.
            include: Optional glob pattern to filter which files are searched (e.g. '*.py', '*.ts').
        """
        try:
            regex = re.compile(pattern)
        except re.error as e:
            return f"Error: Invalid regex pattern: {e}"

        try:
            base = resolve_safe_path(workdir, path)
        except ValueError as e:
            return f"Error: {e}"

        if not base.exists():
            return f"Error: Path not found: {path}"

        # Collect files to search
        if base.is_file():
            files = [base]
        elif include:
            files = sorted(base.rglob(include))
        else:
            files = sorted(base.rglob("*"))

        files = [f for f in files if f.is_file()]

        matches: list[str] = []
        files_with_matches: set[str] = set()

        for file_path in files:
            if len(matches) >= _MAX_RESULTS:
                break

            # Skip binary files
            try:
                head = file_path.read_bytes()[:_BINARY_CHECK_SIZE]
                if b"\x00" in head:
                    continue
            except (PermissionError, OSError):
                continue

            try:
                text = file_path.read_text(encoding="utf-8", errors="replace")
            except (PermissionError, OSError):
                continue

            for line_num, line in enumerate(text.splitlines(), 1):
                if regex.search(line):
                    rel_f = file_path.relative_to(workdir.resolve())
                    matches.append(f"{rel_f}:{line_num}: {line.rstrip()}")
                    files_with_matches.add(str(rel_f))
                    if len(matches) >= _MAX_RESULTS:
                        break

        if not matches:
            return f"No matches for pattern '{pattern}' in {path}"

        header = f"Found matches in {len(files_with_matches)} file(s):\n\n"
        result = header + "\n".join(matches)

        if len(matches) >= _MAX_RESULTS:
            result += f"\n\n... (output capped at {_MAX_RESULTS} matches)"

        return result

    return grep_search


TOOLS = [make_grep_tool(Path("."))]
TOOLS_FACTORY = make_grep_tool

"""Read — read file contents with line numbers."""
from __future__ import annotations

from pathlib import Path

from everstaff.tools.native import tool
from everstaff.tools.path_utils import resolve_safe_path
from everstaff.core.constants import TOOL_MAX_LINE_WIDTH as _MAX_LINE_WIDTH


def _read_permission_hint(args):
    from pathlib import PurePosixPath
    from everstaff.protocols import PermissionHint
    fp = args.get("file_path", "")
    if not fp:
        return PermissionHint("file_path", "*")
    parent = str(PurePosixPath(fp).parent)
    return PermissionHint("file_path", f"{parent}/*")


def make_read_tool(workdir: Path):
    """Return a Read NativeTool scoped to *workdir*."""

    @tool(name="Read", description="Read a file and return its contents with line numbers.",
          permission_hint=_read_permission_hint)
    def read(file_path: str, offset: int = 0, limit: int = 2000) -> str:
        """Read a file, returning lines with line numbers (cat -n style).

        Args:
            file_path: Relative path to the file (within the working directory).
            offset: 0-based line offset to start reading from.
            limit: Maximum number of lines to return (default 2000).
        """
        try:
            p = resolve_safe_path(workdir, file_path)
        except ValueError as e:
            return f"Error: {e}"

        if not p.exists():
            return f"Error: File not found: {file_path}"
        if not p.is_file():
            return f"Error: Not a file: {file_path}"

        try:
            raw = p.read_bytes()
        except PermissionError:
            return f"Error: Permission denied: {file_path}"

        # Binary detection: check for null bytes in first 8KB
        if b"\x00" in raw[:8192]:
            size = len(raw)
            return f"Error: Binary file detected ({size} bytes): {file_path}"

        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text = raw.decode("latin-1")
            except Exception:
                return f"Error: Unable to decode file: {file_path}"

        lines = text.splitlines()
        total = len(lines)

        # Apply offset and limit
        start = max(0, offset)
        end = start + limit
        selected = lines[start:end]

        # Format with line numbers
        output_lines: list[str] = []
        for i, line in enumerate(selected, start=start + 1):
            if len(line) > _MAX_LINE_WIDTH:
                line = line[:_MAX_LINE_WIDTH] + "... (truncated)"
            output_lines.append(f"{i:>6}\t{line}")

        result = "\n".join(output_lines)

        if end < total:
            rel_path = p.relative_to(workdir.resolve())
            result += f"\n\n... ({total - end} more lines not shown, total {total} lines in {rel_path})"

        return result

    return read


TOOLS = [make_read_tool(Path("."))]
TOOLS_FACTORY = make_read_tool

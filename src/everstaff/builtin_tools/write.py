"""Write — create or overwrite files."""
from __future__ import annotations

from pathlib import Path

from everstaff.tools.native import tool
from everstaff.tools.path_utils import resolve_safe_path


def make_write_tool(workdir: Path):
    """Return a Write NativeTool scoped to *workdir*."""

    @tool(name="Write", description="Write content to a file. Creates parent directories if needed.")
    def write(file_path: str, content: str) -> str:
        """Write content to a file, creating parent directories as needed.

        Args:
            file_path: Relative path to the file (within the working directory).
            content: The text content to write.
        """
        try:
            p = resolve_safe_path(workdir, file_path)
        except ValueError as e:
            return f"Error: {e}"

        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            size = len(content.encode("utf-8"))
            return f"Successfully wrote {size} bytes to {file_path}"
        except PermissionError:
            return f"Error: Permission denied: {file_path}"
        except Exception as e:
            return f"Error writing file: {e}"

    return write


TOOLS = [make_write_tool(Path("."))]
TOOLS_FACTORY = make_write_tool

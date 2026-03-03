"""Edit — perform exact string replacements in files."""
from __future__ import annotations

from pathlib import Path

from everstaff.tools.native import tool
from everstaff.tools.path_utils import resolve_safe_path


def _edit_permission_hint(args):
    from pathlib import PurePosixPath
    from everstaff.protocols import PermissionHint
    fp = args.get("file_path", "")
    if not fp:
        return PermissionHint("file_path", "*")
    parent = str(PurePosixPath(fp).parent)
    return PermissionHint("file_path", f"{parent}/*")


def make_edit_tool(workdir: Path):
    """Return an Edit NativeTool scoped to *workdir*."""

    @tool(
        name="Edit",
        description=(
            "Replace exact text in a file. old_string must be unique unless replace_all is True. "
            "All paths must be relative — absolute paths and '..' traversal are not allowed."
        ),
        permission_hint=_edit_permission_hint,
    )
    def edit(
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> str:
        """Replace exact text in a file.

        Args:
            file_path: Relative path to the file to edit within the working directory. Must not start with '/' or contain '..' segments.
            old_string: The exact text to find and replace.
            new_string: The replacement text.
            replace_all: If True, replace all occurrences. If False (default), old_string must appear exactly once.
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
            content = p.read_text(encoding="utf-8")
        except PermissionError:
            return f"Error: Permission denied: {file_path}"
        except UnicodeDecodeError:
            return f"Error: Unable to decode file as UTF-8: {file_path}"

        count = content.count(old_string)

        if count == 0:
            return f"Error: old_string not found in {file_path}"

        if not replace_all and count > 1:
            return (
                f"Error: old_string appears {count} times in {file_path}. "
                f"Provide more context to make it unique, or set replace_all=True."
            )

        new_content = (
            content.replace(old_string, new_string)
            if replace_all
            else content.replace(old_string, new_string, 1)
        )

        try:
            p.write_text(new_content, encoding="utf-8")
        except PermissionError:
            return f"Error: Permission denied writing to {file_path}"

        replaced = count if replace_all else 1
        rel_path = p.relative_to(workdir.resolve())
        return f"Successfully replaced {replaced} occurrence(s) in {rel_path}"

    return edit


TOOLS = [make_edit_tool(Path("."))]
TOOLS_FACTORY = make_edit_tool

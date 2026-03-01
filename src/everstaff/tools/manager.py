"""Tool manager — CRUD + first-directory-wins discovery."""
from __future__ import annotations

import logging
from pathlib import Path

from everstaff.tools.loader import ToolLoader
from everstaff.tools.native import NativeTool

logger = logging.getLogger(__name__)


class ToolManager:
    """Manages tool files: discovery with first-dir-wins dedup, and CRUD."""

    def __init__(self, tools_dirs: list[str]) -> None:
        self._loader = ToolLoader(tools_dirs)
        self._dirs: list[Path] = self._loader._dirs
        self._index: dict[str, tuple[Path, NativeTool]] | None = None

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def discover(self) -> dict[str, tuple[Path, NativeTool]]:
        """Scan all dirs with first-dir-wins dedup. Returns full index."""
        if self._index is not None:
            return self._index
        self._index = {}
        for d in self._dirs:
            for py_file, t in self._loader.scan_dir(d):
                name = t.definition.name
                if name in self._index:
                    logger.warning(
                        "Duplicate tool '%s' — %s ignored, keeping %s",
                        name, py_file, self._index[name][0],
                    )
                    continue
                self._index[name] = (py_file, t)
        return self._index

    def list(self) -> list[dict]:
        result = []
        for p, t in self.discover().values():
            defn = t.definition
            params = []
            # Parameters may be a list of ToolParameter objects or a raw JSON-schema dict
            if isinstance(defn.parameters, list):
                for param in defn.parameters:
                    params.append({
                        "name": param.name,
                        "type": param.type,
                        "description": param.description,
                        "required": param.required,
                    })
            result.append({
                "name": defn.name,
                "description": defn.description,
                "parameters": params,
                "file": str(p),
            })
        return result

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def get_source(self, name: str) -> str:
        entry = self.discover().get(name)
        if not entry:
            raise FileNotFoundError(f"Tool '{name}' not found")
        return entry[0].read_text(encoding="utf-8")

    def create(self, name: str, description: str, content: str | None = None) -> Path:
        primary = self.primary_dir()
        if primary is None:
            raise RuntimeError("No tools directories configured")
        target = primary / f"{name}.py"
        if target.exists():
            raise FileExistsError(f"Tool file already exists: {target}")
        primary.mkdir(parents=True, exist_ok=True)
        target.write_text(content or _default_template(name, description), encoding="utf-8")
        self._invalidate()
        return target

    def update(self, name: str, content: str) -> None:
        entry = self.discover().get(name)
        if not entry:
            raise FileNotFoundError(f"Tool '{name}' not found")
        entry[0].write_text(content, encoding="utf-8")
        self._invalidate()

    def delete(self, name: str) -> None:
        entry = self.discover().get(name)
        if not entry:
            raise FileNotFoundError(f"Tool '{name}' not found")
        entry[0].unlink()
        self._invalidate()

    def primary_dir(self) -> Path | None:
        return self._dirs[0] if self._dirs else None

    def _invalidate(self) -> None:
        self._index = None


def _default_template(name: str, description: str) -> str:
    return f'''\
"""{name} — {description}"""
from __future__ import annotations
from everstaff.tools.native import tool


@tool(name="{name}", description="{description}")
def {name}(arg1: str, arg2: str = "") -> str:
    """Detailed docstring for the LLM."""
    # TODO: implement
    return ""


TOOLS = [{name}]
'''

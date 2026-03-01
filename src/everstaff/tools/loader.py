"""Filesystem-based tool loader — pure FS reader.

Loader responsibility: read .py files, extract NativeTool objects.
Deduplication and CRUD are handled by ToolManager.
"""
from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path
from typing import Any

from everstaff.tools.native import NativeTool

logger = logging.getLogger(__name__)


class ToolLoader:
    """Pure filesystem reader for tool .py files."""

    def __init__(self, tools_dirs: list[str]) -> None:
        # Keep all configured dirs (even if they don't exist yet) so
        # ToolManager.primary_dir() can use the first one for create().
        self._dirs: list[Path] = [Path(d).expanduser().resolve() for d in tools_dirs]
        # Internal index for load() — populated lazily, last-wins across dirs
        self._index: dict[str, tuple[Path, NativeTool]] | None = None

    def scan_dir(self, directory: Path) -> list[tuple[Path, NativeTool]]:
        """Scan a single directory, return all (py_file, NativeTool) pairs.

        No deduplication. Skips files starting with '_'. Logs warnings on
        import errors but does not raise.
        """
        results: list[tuple[Path, NativeTool]] = []
        if not directory.is_dir():
            return results
        for py_file in sorted(directory.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            try:
                for t in self._import_tools_from_file(py_file):
                    results.append((py_file, t))
            except Exception:
                logger.warning("Failed to load tool file: %s", py_file, exc_info=True)
        return results

    def load(self, tool_names: list[str], workdir: Path | None = None) -> list[NativeTool]:
        """Load specific tools by name (whitelist). Used by agent runtime."""
        self._ensure_index()
        assert self._index is not None
        result: list[NativeTool] = []
        for name in tool_names:
            entry = self._index.get(name)
            if entry is None:
                logger.warning(
                    "Tool '%s' not found. Available: %s",
                    name, ", ".join(sorted(self._index.keys())),
                )
                continue
            py_file, cached_tool = entry
            if workdir is not None:
                module = self._import_module_by_path(py_file)
                factory = getattr(module, "TOOLS_FACTORY", None)
                if factory is not None:
                    result.append(factory(workdir))
                    continue
            result.append(cached_tool)
        return result

    def _ensure_index(self) -> None:
        if self._index is not None:
            return
        self._index = {}
        for d in self._dirs:
            for py_file, t in self.scan_dir(d):
                self._index[t.definition.name] = (py_file, t)  # last-wins

    @staticmethod
    def _import_module_by_path(py_file: Path):
        module_name = f"_agent_tool_factory_{py_file.stem}"
        if module_name in sys.modules:
            return sys.modules[module_name]
        spec = importlib.util.spec_from_file_location(module_name, py_file)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load {py_file}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module

    @staticmethod
    def _import_tools_from_file(py_file: Path) -> list[NativeTool]:
        module_name = f"_agent_tools_{py_file.stem}"
        spec = importlib.util.spec_from_file_location(module_name, py_file)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot create module spec for {py_file}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
            tools_attr: Any = getattr(module, "TOOLS", None)
            factory_attr: Any = getattr(module, "TOOLS_FACTORY", None)
            if tools_attr is None:
                if factory_attr is None:
                    logger.debug("No TOOLS list in %s — skipping", py_file)
                    return []
                # Discover via TOOLS_FACTORY with a placeholder workdir
                try:
                    placeholder = factory_attr(Path("."))
                    if isinstance(placeholder, NativeTool):
                        logger.debug("Discovered tool via TOOLS_FACTORY in %s", py_file)
                        return [placeholder]
                except Exception as exc:
                    logger.warning("TOOLS_FACTORY discovery failed in %s: %s", py_file, exc)
                return []
            if not isinstance(tools_attr, (list, tuple)):
                logger.warning("TOOLS in %s is not a list — skipping", py_file)
                return []
            result: list[NativeTool] = []
            for item in tools_attr:
                if isinstance(item, NativeTool):
                    result.append(item)
                elif callable(item):
                    # TOOLS item may be a factory function — call with placeholder workdir
                    try:
                        placeholder = item(Path("."))
                        if isinstance(placeholder, NativeTool):
                            result.append(placeholder)
                            continue
                    except Exception:
                        pass
                    logger.warning(
                        "Non-NativeTool item in TOOLS list of %s: %s — skipping",
                        py_file, type(item).__name__,
                    )
                else:
                    logger.warning(
                        "Non-NativeTool item in TOOLS list of %s: %s — skipping",
                        py_file, type(item).__name__,
                    )
            return result
        finally:
            sys.modules.pop(module_name, None)

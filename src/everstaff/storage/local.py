"""LocalFileStore — FileStore implementation backed by the local filesystem."""
from __future__ import annotations

from pathlib import Path


class LocalFileStore:
    """FileStore backed by local filesystem. Paths are relative to base_dir."""

    def __init__(self, base_dir: str | Path) -> None:
        self._base = Path(base_dir)
        self._base.mkdir(parents=True, exist_ok=True)

    def _resolve(self, path: str) -> Path:
        resolved = (self._base / path).resolve()
        try:
            resolved.relative_to(self._base.resolve())
        except ValueError:
            raise ValueError(f"Path {path!r} escapes base directory")
        return resolved

    async def read(self, path: str) -> bytes:
        return self._resolve(path).read_bytes()

    async def write(self, path: str, data: bytes) -> None:
        full = self._resolve(path)
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_bytes(data)

    async def append(self, path: str, data: bytes) -> None:
        full = self._resolve(path)
        full.parent.mkdir(parents=True, exist_ok=True)
        with full.open("ab") as f:
            f.write(data)

    async def exists(self, path: str) -> bool:
        return self._resolve(path).exists()

    async def delete(self, path: str) -> None:
        p = self._resolve(path)
        if p.exists():
            p.unlink()

    async def list(self, prefix: str) -> list[str]:
        """List all paths under the given prefix (relative to base_dir)."""
        prefix_path = self._resolve(prefix)  # raises ValueError if escape attempt
        if not prefix_path.exists():
            return []
        base_resolved = self._base.resolve()
        results = []
        for item in prefix_path.rglob("*"):
            if item.is_file():
                # Also filter out symlinks pointing outside base_dir
                try:
                    item_resolved = item.resolve()
                    item_resolved.relative_to(base_resolved)
                    results.append(str(item_resolved.relative_to(base_resolved)))
                except ValueError:
                    pass  # skip files that escape via symlink
        return results

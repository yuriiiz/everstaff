"""JSONL-based session index for fast listing and path resolution."""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class IndexEntry:
    id: str
    root: str                   # == id for root sessions
    parent: str | None = None
    agent: str = ""
    agent_uuid: str | None = None
    status: str = "running"
    created_at: str = ""
    updated_at: str = ""


class SessionIndex:
    """Append-only JSONL index over session metadata.

    File: ``{sessions_dir}/_index.jsonl``

    Each line is a JSON object keyed by ``id``.  On ``upsert`` the new entry
    is appended; ``compact()`` rewrites the file keeping only the latest
    entry per id.  Reads replay the full file into an in-memory dict.
    """

    def __init__(self, sessions_dir: Path) -> None:
        self._dir = sessions_dir
        self._path = sessions_dir / "_index.jsonl"
        self._entries: dict[str, IndexEntry] = {}
        self._dirty = False
        if self._path.exists():
            self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, session_id: str) -> IndexEntry | None:
        return self._entries.get(session_id)

    def upsert(self, entry: IndexEntry) -> None:
        self._entries[entry.id] = entry
        self._append(entry)

    def remove(self, session_id: str) -> None:
        if session_id in self._entries:
            del self._entries[session_id]
            self._dirty = True
            self.compact()

    def list_roots(
        self,
        *,
        status: str | None = None,
        agent_uuid: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[IndexEntry]:
        roots = [e for e in self._entries.values() if e.root == e.id]
        if status:
            roots = [e for e in roots if e.status == status]
        if agent_uuid:
            roots = [e for e in roots if e.agent_uuid == agent_uuid]
        # Sort by created_at descending (newest first)
        roots.sort(key=lambda e: e.created_at, reverse=True)
        return roots[offset : offset + limit]

    def children_of(self, root_id: str) -> list[IndexEntry]:
        return [e for e in self._entries.values()
                if e.root == root_id and e.id != root_id]

    def root_of(self, session_id: str) -> str | None:
        entry = self._entries.get(session_id)
        return entry.root if entry else None

    def rebuild(self) -> None:
        """Rebuild index by scanning the sessions directory."""
        self._entries.clear()
        if not self._dir.exists():
            return
        for child in self._dir.iterdir():
            if not child.is_dir() or child.name.startswith("_"):
                continue
            root_id = child.name
            session_file = child / "session.json"
            if session_file.exists():
                entry = self._parse_session_file(session_file, root_id, root_id)
                if entry:
                    self._entries[entry.id] = entry
            # Scan sub_sessions/
            sub_dir = child / "sub_sessions"
            if sub_dir.is_dir():
                for sub_file in sub_dir.iterdir():
                    if sub_file.suffix == ".json" and sub_file.is_file():
                        child_id = sub_file.stem
                        entry = self._parse_session_file(sub_file, child_id, root_id)
                        if entry:
                            self._entries[entry.id] = entry
        self._rewrite()

    def compact(self) -> None:
        """Rewrite the JSONL file keeping only the latest entry per id."""
        self._rewrite()

    # ------------------------------------------------------------------
    # Static path helpers
    # ------------------------------------------------------------------

    @staticmethod
    def session_relpath(session_id: str, root_session_id: str | None) -> str:
        """FileStore-relative path for session data."""
        if root_session_id and root_session_id != session_id:
            return f"{root_session_id}/sub_sessions/{session_id}.json"
        return f"{session_id}/session.json"

    @staticmethod
    def signal_relpath(session_id: str, root_session_id: str | None) -> str:
        """Only root sessions have cancel.signal files."""
        root = root_session_id or session_id
        return f"{root}/cancel.signal"

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load(self) -> None:
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        entry = IndexEntry(**{k: v for k, v in data.items()
                                              if k in IndexEntry.__dataclass_fields__})
                        self._entries[entry.id] = entry
                    except (json.JSONDecodeError, TypeError):
                        continue
        except OSError:
            pass

    def _append(self, entry: IndexEntry) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")

    def _rewrite(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            for entry in self._entries.values():
                f.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")
        tmp.replace(self._path)
        self._dirty = False

    @staticmethod
    def _parse_session_file(path: Path, session_id: str, root_id: str) -> IndexEntry | None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return None
            return IndexEntry(
                id=data.get("session_id", session_id),
                root=data.get("root_session_id", root_id),
                parent=data.get("parent_session_id"),
                agent=data.get("agent_name", ""),
                agent_uuid=data.get("agent_uuid"),
                status=data.get("status", "unknown"),
                created_at=data.get("created_at", ""),
                updated_at=data.get("updated_at", ""),
            )
        except Exception:
            return None

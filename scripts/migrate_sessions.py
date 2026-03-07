#!/usr/bin/env python3
"""Migrate flat session layout to grouped layout with JSONL index.

Old layout (flat):
    sessions_dir/
        {session_id}/session.json       # every session gets its own directory
        {session_id}/workspaces/        # per-session workspace
        {session_id}/cancel.signal

New layout (grouped):
    sessions_dir/
        _index.jsonl                    # fast lookup index
        {root_id}/
            session.json                # root session data
            workspaces/                 # SHARED by all descendants
            cancel.signal               # only root has signal
            sub_sessions/
                {child_id}.json         # child stored as plain file
                {grandchild_id}.json

Usage:
    python scripts/migrate_sessions.py /path/to/sessions_dir
    python scripts/migrate_sessions.py /path/to/sessions_dir --dry-run
    python scripts/migrate_sessions.py /path/to/sessions_dir --verbose
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("migrate_sessions")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@dataclass
class IndexEntry:
    id: str
    root: str
    parent: str | None = None
    agent: str = ""
    agent_uuid: str | None = None
    status: str = "running"
    created_at: str = ""
    updated_at: str = ""


def read_session(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def write_session(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_index(sessions_dir: Path, entries: list[IndexEntry]) -> None:
    index_path = sessions_dir / "_index.jsonl"
    with open(index_path, "w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")
    logger.info("Wrote _index.jsonl with %d entries", len(entries))


# ---------------------------------------------------------------------------
# Migration logic
# ---------------------------------------------------------------------------

def discover_sessions(sessions_dir: Path) -> dict[str, dict]:
    """Scan flat layout and load all session.json files."""
    sessions: dict[str, dict] = {}
    for child in sorted(sessions_dir.iterdir()):
        if not child.is_dir() or child.name.startswith("_"):
            continue
        session_file = child / "session.json"
        if not session_file.exists():
            continue
        data = read_session(session_file)
        if data is None:
            logger.warning("  skip unreadable: %s", session_file)
            continue
        sid = data.get("session_id", child.name)
        sessions[sid] = data
    return sessions


def resolve_root(session_id: str, sessions: dict[str, dict]) -> str:
    """Walk parent_session_id chain to find the root session."""
    visited: set[str] = set()
    current = session_id
    while current in sessions:
        if current in visited:
            logger.warning("  cycle detected at %s, using as root", current)
            break
        visited.add(current)
        parent = sessions[current].get("parent_session_id")
        if not parent or parent not in sessions:
            break
        current = parent
    return current


def classify_sessions(
    sessions: dict[str, dict],
) -> tuple[dict[str, str], set[str]]:
    """Return (child_id -> root_id mapping, set of root ids)."""
    child_to_root: dict[str, str] = {}
    roots: set[str] = set()

    for sid, data in sessions.items():
        root_id = resolve_root(sid, sessions)
        if root_id == sid:
            roots.add(sid)
        else:
            child_to_root[sid] = root_id

    # Ensure every root referenced by a child actually IS a root
    for child_id, root_id in child_to_root.items():
        roots.add(root_id)

    return child_to_root, roots


def migrate(sessions_dir: Path, *, dry_run: bool = False) -> None:
    logger.info("Scanning %s ...", sessions_dir)
    sessions = discover_sessions(sessions_dir)
    logger.info("Found %d session(s)", len(sessions))

    if not sessions:
        logger.info("Nothing to migrate.")
        return

    child_to_root, roots = classify_sessions(sessions)
    orphan_children: dict[str, str] = {}

    # Check for children whose parent directory doesn't exist as a session
    for child_id, root_id in list(child_to_root.items()):
        if root_id not in sessions:
            logger.warning(
                "  child %s references root %s which has no session.json — "
                "promoting child to root",
                child_id[:8], root_id[:8],
            )
            orphan_children[child_id] = root_id
            del child_to_root[child_id]
            roots.add(child_id)

    logger.info(
        "Classification: %d root(s), %d child(ren), %d orphan(s)",
        len(roots), len(child_to_root), len(orphan_children),
    )

    # Check which sessions are already in new layout
    already_migrated = set()
    for sid in list(child_to_root.keys()):
        root_id = child_to_root[sid]
        new_path = sessions_dir / root_id / "sub_sessions" / f"{sid}.json"
        old_path = sessions_dir / sid / "session.json"
        if new_path.exists() and not old_path.exists():
            already_migrated.add(sid)

    if already_migrated:
        logger.info("  %d child session(s) already migrated, skipping", len(already_migrated))
        for sid in already_migrated:
            del child_to_root[sid]

    if not child_to_root and not orphan_children:
        logger.info("All sessions are roots or already migrated.")
        # Still rebuild index
        if not dry_run:
            entries = _build_index_entries(sessions_dir, sessions, {}, roots)
            write_index(sessions_dir, entries)
        return

    # --- Execute migration ---

    moved_count = 0
    workspace_merged_count = 0
    errors = 0

    for child_id, root_id in sorted(child_to_root.items()):
        child_dir = sessions_dir / child_id
        child_session_file = child_dir / "session.json"
        new_path = sessions_dir / root_id / "sub_sessions" / f"{child_id}.json"

        if not child_session_file.exists():
            logger.warning("  skip %s: session.json missing", child_id[:8])
            errors += 1
            continue

        data = sessions[child_id]
        # Inject root_session_id
        data["root_session_id"] = root_id

        logger.info(
            "  move %s → %s/sub_sessions/%s.json",
            child_id[:8], root_id[:8], child_id[:8],
        )

        if not dry_run:
            try:
                write_session(new_path, data)
            except Exception as e:
                logger.error("  FAILED to write %s: %s", new_path, e)
                errors += 1
                continue

        # Merge workspace into root's workspace
        child_workspace = child_dir / "workspaces"
        if child_workspace.is_dir() and any(child_workspace.iterdir()):
            root_workspace = sessions_dir / root_id / "workspaces"
            logger.info(
                "  merge workspace %s → %s",
                child_id[:8], root_id[:8],
            )
            if not dry_run:
                root_workspace.mkdir(parents=True, exist_ok=True)
                for item in child_workspace.iterdir():
                    dest = root_workspace / item.name
                    if dest.exists():
                        logger.warning(
                            "    workspace conflict: %s already exists in root, skipping",
                            item.name,
                        )
                        continue
                    try:
                        if item.is_dir():
                            shutil.copytree(item, dest)
                        else:
                            shutil.copy2(item, dest)
                    except Exception as e:
                        logger.error("    FAILED to copy %s: %s", item.name, e)
                        errors += 1
                        continue
            workspace_merged_count += 1

        # Remove old child directory
        if not dry_run:
            try:
                shutil.rmtree(child_dir)
                logger.debug("  removed old dir %s/", child_id[:8])
            except Exception as e:
                logger.error("  FAILED to remove %s: %s", child_dir, e)
                errors += 1

        moved_count += 1

    # Inject root_session_id into root sessions (set to their own id or null)
    for root_id in roots:
        if root_id not in sessions:
            continue
        session_file = sessions_dir / root_id / "session.json"
        if not session_file.exists():
            continue
        data = sessions[root_id]
        if "root_session_id" not in data or data.get("root_session_id") is None:
            data["root_session_id"] = root_id
            if not dry_run:
                try:
                    write_session(session_file, data)
                except Exception as e:
                    logger.error("  FAILED to update root %s: %s", root_id[:8], e)
                    errors += 1

    # Rebuild index
    if not dry_run:
        entries = _build_index_entries(sessions_dir, sessions, child_to_root, roots)
        write_index(sessions_dir, entries)

    # Summary
    logger.info("--- Migration summary ---")
    logger.info("  Sessions scanned : %d", len(sessions))
    logger.info("  Root sessions    : %d", len(roots))
    logger.info("  Children moved   : %d", moved_count)
    logger.info("  Workspaces merged: %d", workspace_merged_count)
    logger.info("  Already migrated : %d", len(already_migrated))
    if errors:
        logger.warning("  Errors           : %d", errors)
    if dry_run:
        logger.info("  (dry run — no files were modified)")


def _build_index_entries(
    sessions_dir: Path,
    sessions: dict[str, dict],
    child_to_root: dict[str, str],
    roots: set[str],
) -> list[IndexEntry]:
    """Build IndexEntry list from migrated data."""
    entries: list[IndexEntry] = []

    # Root entries
    for root_id in roots:
        data = sessions.get(root_id)
        if data is None:
            continue
        entries.append(IndexEntry(
            id=root_id,
            root=root_id,
            parent=None,
            agent=data.get("agent_name", ""),
            agent_uuid=data.get("agent_uuid"),
            status=data.get("status", "unknown"),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        ))

    # Child entries
    for child_id, root_id in child_to_root.items():
        data = sessions.get(child_id)
        if data is None:
            continue
        entries.append(IndexEntry(
            id=child_id,
            root=root_id,
            parent=data.get("parent_session_id"),
            agent=data.get("agent_name", ""),
            agent_uuid=data.get("agent_uuid"),
            status=data.get("status", "unknown"),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        ))

    # Also scan for already-migrated children in sub_sessions/
    for root_id in roots:
        sub_dir = sessions_dir / root_id / "sub_sessions"
        if not sub_dir.is_dir():
            continue
        for f in sub_dir.iterdir():
            if f.suffix != ".json" or not f.is_file():
                continue
            cid = f.stem
            if cid in {e.id for e in entries}:
                continue  # already included
            data = read_session(f)
            if data is None:
                continue
            entries.append(IndexEntry(
                id=cid,
                root=root_id,
                parent=data.get("parent_session_id"),
                agent=data.get("agent_name", ""),
                agent_uuid=data.get("agent_uuid"),
                status=data.get("status", "unknown"),
                created_at=data.get("created_at", ""),
                updated_at=data.get("updated_at", ""),
            ))

    return entries


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate flat session layout to grouped layout with JSONL index.",
    )
    parser.add_argument(
        "sessions_dir",
        type=Path,
        help="Path to the sessions directory",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without modifying files",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args()

    logger.setLevel(logging.DEBUG if args.verbose else logging.INFO)

    sessions_dir = args.sessions_dir.expanduser().resolve()
    if not sessions_dir.is_dir():
        logger.error("Not a directory: %s", sessions_dir)
        sys.exit(1)

    migrate(sessions_dir, dry_run=args.dry_run)


if __name__ == "__main__":
    main()

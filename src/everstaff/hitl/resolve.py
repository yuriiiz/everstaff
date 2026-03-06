"""Canonical HITL resolution — single entry point for all resolve paths."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from everstaff.protocols import FileStore
    from everstaff.schema.api_models import HitlResolution

logger = logging.getLogger(__name__)


class HitlNotFoundError(Exception):
    pass


class HitlAlreadyResolvedError(Exception):
    pass


class HitlExpiredError(Exception):
    pass


def _is_expired(hitl_item: dict) -> bool:
    timeout = hitl_item.get("timeout_seconds", 86400)
    if timeout == 0:
        return False
    created_raw = hitl_item.get("created_at", "")
    if not created_raw:
        return False
    try:
        created_at = datetime.fromisoformat(created_raw)
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - created_at).total_seconds() > timeout
    except Exception:
        return False


async def _resolve_in_origin(
    hitl_id: str,
    origin_session_id: str,
    resolution_dump: dict,
    *,
    file_store: "FileStore",
    session_index=None,
) -> None:
    """Best-effort: also mark the HITL as resolved in the origin (child) session."""
    from everstaff.session.index import SessionIndex

    # Resolve root for path
    origin_root = None
    if session_index:
        entry = session_index.get(origin_session_id)
        if entry and entry.root != origin_session_id:
            origin_root = entry.root

    origin_path = SessionIndex.session_relpath(origin_session_id, origin_root)
    try:
        raw = await file_store.read(origin_path)
        origin_data = json.loads(raw.decode())
    except Exception:
        return

    changed = False
    for item in origin_data.get("hitl_requests", []):
        if item.get("hitl_id") == hitl_id and item.get("status") == "pending":
            item["status"] = "resolved"
            item["response"] = resolution_dump
            changed = True
            break

    if changed:
        await file_store.write(
            origin_path,
            json.dumps(origin_data, ensure_ascii=False, indent=2).encode(),
        )


async def resolve_hitl(
    session_id: str,
    hitl_id: str,
    decision: str,
    comment: str | None = None,
    resolved_by: str = "human",
    grant_scope: str | None = None,
    permission_pattern: str | None = None,
    *,
    file_store: "FileStore",
    root_session_id: str | None = None,
    session_index=None,
) -> "HitlResolution":
    """The one and only resolve implementation.

    Returns HitlResolution and persists it to session.json.
    Raises HitlNotFoundError, HitlAlreadyResolvedError, HitlExpiredError.
    """
    from everstaff.schema.api_models import HitlResolution
    from everstaff.session.index import SessionIndex

    session_path = SessionIndex.session_relpath(session_id, root_session_id)
    raw = await file_store.read(session_path)
    session_data = json.loads(raw.decode())

    target = None
    for item in session_data.get("hitl_requests", []):
        if item.get("hitl_id") == hitl_id:
            target = item
            break

    if target is None:
        raise HitlNotFoundError(f"HITL request '{hitl_id}' not found in session {session_id}")

    if target.get("status") != "pending":
        raise HitlAlreadyResolvedError(f"HITL request '{hitl_id}' is already {target.get('status')}")

    if _is_expired(target):
        raise HitlExpiredError(f"HITL request '{hitl_id}' has expired")

    resolution = HitlResolution(
        decision=decision,
        comment=comment,
        resolved_at=datetime.now(timezone.utc),
        resolved_by=resolved_by,
        grant_scope=grant_scope,
        permission_pattern=permission_pattern,
    )
    target["status"] = "resolved"
    target["response"] = resolution.model_dump(mode="json")

    await file_store.write(
        session_path,
        json.dumps(session_data, ensure_ascii=False, indent=2).encode(),
    )

    # If this HITL was escalated from a child session, also resolve the
    # child's copy so the UI shows it as resolved everywhere.
    origin_sid = target.get("origin_session_id", "")
    if origin_sid and origin_sid != session_id:
        try:
            await _resolve_in_origin(
                hitl_id, origin_sid, resolution.model_dump(mode="json"),
                file_store=file_store, session_index=session_index,
            )
        except Exception:
            logger.debug("Failed to resolve origin HITL %s in %s", hitl_id, origin_sid, exc_info=True)

    return resolution


def all_hitls_settled(session_data: dict) -> bool:
    """Check if all HITL requests in a session are resolved/expired."""
    return all(
        item.get("status") != "pending"
        for item in session_data.get("hitl_requests", [])
    )

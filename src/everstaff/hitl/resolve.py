"""Canonical HITL resolution — single entry point for all resolve paths."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from everstaff.protocols import FileStore
    from everstaff.schema.api_models import HitlResolution


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


async def resolve_hitl(
    session_id: str,
    hitl_id: str,
    decision: str,
    comment: str | None = None,
    resolved_by: str = "human",
    grant_scope: str | None = None,
    *,
    file_store: "FileStore",
) -> "HitlResolution":
    """The one and only resolve implementation.

    Returns HitlResolution and persists it to session.json.
    Raises HitlNotFoundError, HitlAlreadyResolvedError, HitlExpiredError.
    """
    from everstaff.schema.api_models import HitlResolution

    session_path = f"{session_id}/session.json"
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
    )
    target["status"] = "resolved"
    target["response"] = resolution.model_dump(mode="json")

    await file_store.write(
        session_path,
        json.dumps(session_data, ensure_ascii=False, indent=2).encode(),
    )

    return resolution


def all_hitls_settled(session_data: dict) -> bool:
    """Check if all HITL requests in a session are resolved/expired."""
    return all(
        item.get("status") != "pending"
        for item in session_data.get("hitl_requests", [])
    )

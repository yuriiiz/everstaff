"""HITL API — list pending human approval requests and submit decisions."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from pydantic import BaseModel

from everstaff.schema.api_models import HitlResolution
from everstaff.hitl.resolve import (
    resolve_hitl as canonical_resolve,
    all_hitls_settled,
    HitlNotFoundError,
    HitlAlreadyResolvedError,
    HitlExpiredError,
)


class HitlDecision(BaseModel):
    decision: str                    # "approved" | "rejected" | option text | free text
    comment: Optional[str] = None
    resolved_by: str = "human"
    grant_scope: Optional[str] = None


def _is_expired(hitl_item: dict) -> bool:
    """Return True if this HITL request has timed out (lazy check)."""
    timeout = hitl_item.get("timeout_seconds", 86400)
    if timeout == 0:
        return False  # no timeout
    created_raw = hitl_item.get("created_at", "")
    if not created_raw:
        return False
    try:
        created_at = datetime.fromisoformat(created_raw)
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - created_at).total_seconds()
        return age > timeout
    except Exception:
        return False


async def _find_hitl_in_sessions(store, hitl_id: str) -> tuple[str | None, dict | None, dict | None]:
    """Find a HITL request by hitl_id scanning session.json files.

    Returns (session_id, hitl_item, session_data) or (None, None, None).
    """
    try:
        paths = await store.list("")
    except Exception:
        return None, None, None

    for path in paths:
        if not path.endswith("/session.json"):
            continue
        try:
            raw = await store.read(path)
            session_data = json.loads(raw.decode())
        except Exception:
            continue

        for item in session_data.get("hitl_requests", []):
            if item.get("hitl_id") == hitl_id:
                sid = session_data.get("session_id", path.replace("/session.json", ""))
                return sid, item, session_data

    return None, None, None


async def _save_session_json(store, session_id: str, session_data: dict) -> None:
    """Write updated session_data back to session.json."""
    path = f"{session_id}/session.json"
    await store.write(path, json.dumps(session_data, ensure_ascii=False, indent=2).encode())


async def _resolve_hitl_internal(app, hitl_id: str, decision: str, comment=None, broadcast_fn=None) -> None:
    """Resolve a HITL request — shared by REST endpoint and WS handler."""
    store = app.state.file_store
    config = app.state.config
    channel_manager = getattr(app.state, "channel_manager", None)

    session_id, hitl_item, session_data = await _find_hitl_in_sessions(store, hitl_id)
    if session_id is None or hitl_item is None:
        return
    if hitl_item.get("status") != "pending":
        return
    if _is_expired(hitl_item):
        return

    try:
        await canonical_resolve(
            session_id=session_id,
            hitl_id=hitl_id,
            decision=decision,
            comment=comment,
            file_store=store,
        )
    except Exception:
        return

    # Re-read session data to check settlement
    try:
        raw = await store.read(f"{session_id}/session.json")
        session_data = json.loads(raw.decode())
    except Exception:
        return

    if not all_hitls_settled(session_data):
        return

    agent_name = session_data.get("agent_name", "")
    from everstaff.api.sessions import _resume_session_task
    await _resume_session_task(session_id, agent_name, "", config, broadcast_fn=broadcast_fn, channel_manager=channel_manager)


def make_router(config) -> APIRouter:
    router = APIRouter(tags=["hitl"], prefix="/hitl")

    @router.get("")
    async def list_pending(request: Request) -> list[dict]:
        """List all pending HITL requests from session.json files."""
        store = request.app.state.file_store
        pending = []
        try:
            paths = await store.list("")
        except Exception:
            return pending

        for path in paths:
            if not path.endswith("/session.json"):
                continue
            try:
                raw = await store.read(path)
                session_data = json.loads(raw.decode())
            except Exception:
                continue

            if session_data.get("status") != "waiting_for_human":
                continue

            for item in session_data.get("hitl_requests", []):
                if item.get("status") != "pending":
                    continue
                if _is_expired(item):
                    continue
                # Enrich with session metadata for callers
                enriched = dict(item)
                enriched.setdefault("session_id", session_data.get("session_id", ""))
                enriched.setdefault("agent_name", session_data.get("agent_name", ""))
                pending.append(enriched)

        return pending

    @router.get("/{hitl_id}")
    async def get_hitl_request(hitl_id: str, request: Request) -> dict:
        """Find a specific HITL request by hitl_id."""
        store = request.app.state.file_store
        session_id, hitl_item, session_data = await _find_hitl_in_sessions(store, hitl_id)
        if session_id is None:
            raise HTTPException(status_code=404, detail=f"HITL request '{hitl_id}' not found")
        enriched = dict(hitl_item)
        enriched.setdefault("session_id", session_id)
        return enriched

    @router.post("/{hitl_id}/resolve")
    async def resolve_hitl(
        hitl_id: str,
        decision: HitlDecision,
        request: Request,
        background_tasks: BackgroundTasks,
        auto_resume: bool = Query(default=True),
    ) -> dict:
        """Submit a human decision. Resumes the session when all HITLs are settled."""
        store = request.app.state.file_store

        session_id, hitl_item, session_data = await _find_hitl_in_sessions(store, hitl_id)
        if session_id is None:
            raise HTTPException(status_code=404, detail=f"HITL request '{hitl_id}' not found")

        try:
            await canonical_resolve(
                session_id=session_id,
                hitl_id=hitl_id,
                decision=decision.decision,
                comment=decision.comment,
                resolved_by=decision.resolved_by,
                file_store=store,
            )
        except HitlNotFoundError:
            raise HTTPException(status_code=404, detail=f"HITL request '{hitl_id}' not found")
        except HitlAlreadyResolvedError:
            raise HTTPException(status_code=409, detail="HITL request already resolved")
        except HitlExpiredError:
            raise HTTPException(status_code=410, detail="HITL request has expired")

        # Re-read session data for updated hitl_item and settlement check
        raw = await store.read(f"{session_id}/session.json")
        session_data = json.loads(raw.decode())
        updated_item = next(
            (i for i in session_data.get("hitl_requests", []) if i.get("hitl_id") == hitl_id),
            {},
        )

        if auto_resume and all_hitls_settled(session_data):
            import everstaff.api.sessions as _sessions_mod
            agent_name = session_data.get("agent_name", "")
            cm = getattr(request.app.state, "channel_manager", None)
            broadcast_fn = None
            if cm:
                try:
                    from everstaff.channels.websocket import WebSocketChannel
                    for ch in cm._channels:
                        if isinstance(ch, WebSocketChannel):
                            broadcast_fn = ch._broadcast
                            break
                except Exception:
                    pass
            background_tasks.add_task(
                _sessions_mod._resume_session_task, session_id, agent_name, "", config,
                broadcast_fn=broadcast_fn,
                channel_manager=cm,
            )

        return dict(updated_item)

    return router

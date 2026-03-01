"""Lark/Feishu webhook handler."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Request

logger = logging.getLogger(__name__)

router = APIRouter(tags=["webhooks"])


@router.post("/webhooks/lark")
async def lark_webhook(req: Request, background_tasks: BackgroundTasks) -> dict:
    """Receive Lark interactive card callbacks and resolve HITL requests."""
    try:
        body = await req.json()
    except Exception:
        return {"msg": "bad request"}

    if body.get("type") == "url_verification":
        return {"challenge": body.get("challenge", "")}

    body_token = body.get("token", "")
    _lark_channels = getattr(req.app.state, "lark_channels", [])
    if _lark_channels:
        if not any(ch.verify_webhook(body_token) for ch in _lark_channels):
            return {"msg": "unauthorized"}

    action = body.get("action", {})
    value = action.get("value", {})
    hitl_id = value.get("hitl_id")
    decision = value.get("decision")

    if not hitl_id or not decision:
        return {"msg": "ignored"}

    _channel_manager = getattr(req.app.state, "channel_manager", None)
    if _channel_manager is None:
        return {"msg": "no channel manager"}

    if decision == "__input__":
        form_value = action.get("form_value", {})
        decision = form_value.get("user_input", "")

    operator = body.get("operator", {})
    resolved_by = operator.get("open_id", "lark_user")

    from everstaff.protocols import HitlResolution
    resolution = HitlResolution(
        decision=decision,
        resolved_at=datetime.now(timezone.utc),
        resolved_by=resolved_by,
    )
    await _channel_manager.resolve(hitl_id, resolution)

    from everstaff.api.hitl import _resolve_hitl_internal
    background_tasks.add_task(
        _resolve_hitl_internal,
        req.app,
        hitl_id,
        decision,
        None,  # comment
    )

    return {"msg": "ok"}

"""Lark/Feishu webhook handler."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request

logger = logging.getLogger(__name__)

router = APIRouter(tags=["webhooks"])


@router.post("/webhooks/lark")
async def lark_webhook(req: Request) -> dict:
    """Receive Lark interactive card callbacks and resolve HITL requests."""
    try:
        body = await req.json()
    except Exception:
        return {"msg": "bad request"}

    logger.info("lark_webhook body=%s", body)

    if body.get("type") == "url_verification":
        return {"challenge": body.get("challenge", "")}

    body_token = body.get("token", "")
    _lark_channels = getattr(req.app.state, "lark_channels", [])
    if _lark_channels:
        if not any(ch.verify_webhook(body_token) for ch in _lark_channels):
            logger.warning("lark_webhook unauthorized token")
            return {"msg": "unauthorized"}

    action = body.get("action", {})
    value = action.get("value", {})
    hitl_id = value.get("hitl_id")
    decision = value.get("decision")
    grant_scope = value.get("grant_scope")
    permission_pattern = value.get("permission_pattern")

    if not hitl_id or not decision:
        logger.info("lark_webhook ignored: hitl_id=%s decision=%s", hitl_id, decision)
        return {"msg": "ignored"}

    _channel_manager = getattr(req.app.state, "channel_manager", None)
    if _channel_manager is None:
        logger.warning("lark_webhook no channel_manager")
        return {"msg": "no channel manager"}

    if decision == "__input__":
        form_value = action.get("form_value", {})
        decision = form_value.get("user_input", "")

    operator = body.get("operator", {})
    resolved_by = operator.get("open_id", "lark_user")

    logger.info("lark_webhook resolving hitl_id=%s decision=%r by=%s grant_scope=%s", hitl_id, decision, resolved_by, grant_scope)

    from everstaff.protocols import HitlResolution
    resolution = HitlResolution(
        decision=decision,
        resolved_at=datetime.now(timezone.utc),
        resolved_by=resolved_by,
        grant_scope=grant_scope,
        permission_pattern=permission_pattern,
    )
    await _channel_manager.resolve(hitl_id, resolution)

    # Return a toast to give the user immediate feedback in Lark
    return {
        "toast": {"type": "success", "content": f"Decision: {decision}"},
    }

"""Shared auth-retry helper for Feishu tools."""
from __future__ import annotations

from typing import Any, Awaitable, Callable


async def call_with_auth_retry(
    *,
    fn: Callable[[str], Awaitable[Any]],
    user_open_id: str,
    app_id: str,
    app_secret: str,
    domain: str,
    token_store: Any,
    required_scopes: list[str],
    auth_handler: Any | None,
    base_scopes: list[str] | None = None,
    include_offline_access: bool = True,
) -> str:
    """Call fn via UAT, handling auth errors with blocking poll + auto-retry.

    If no token or scopes are insufficient, initiates Device Flow, blocks
    up to 3 minutes waiting for user authorization, then retries the call.
    """
    from everstaff.tools.feishu.uat_client import call_with_uat
    from everstaff.tools.feishu.errors import UserAuthRequiredError

    try:
        return await call_with_uat(
            user_open_id=user_open_id, app_id=app_id, app_secret=app_secret,
            domain=domain, fn=fn, token_store=token_store,
            required_scopes=required_scopes,
        )
    except UserAuthRequiredError as e:
        if auth_handler is None:
            raise
        from everstaff.tools.feishu.auto_auth import handle_auth_error
        e.required_scopes = e.required_scopes or required_scopes
        result = await handle_auth_error(
            err=e, app_id=app_id, app_secret=app_secret, domain=domain,
            send_card_fn=auth_handler.send_card,
            update_card_fn=auth_handler.update_card,
            send_text_fn=getattr(auth_handler, "send_text", None),
            token_store=token_store,
            base_scopes=base_scopes,
            include_offline_access=include_offline_access,
        )
        if result.get("authorized"):
            # Auth succeeded — retry the original call
            return await call_with_uat(
                user_open_id=user_open_id, app_id=app_id, app_secret=app_secret,
                domain=domain, fn=fn, token_store=token_store,
                required_scopes=required_scopes,
            )
        return result.get("message", "❌ 授权失败")

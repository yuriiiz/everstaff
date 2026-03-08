"""Auto-auth middleware: intercepts tool auth errors and resolves via HITL cards.

When a Feishu tool call fails due to missing user authorization, this module:
1. Initiates OAuth Device Flow
2. Sends an auth card to the user via the Lark channel
3. Polls for token in background
4. Stores the token and signals completion
"""
from __future__ import annotations

import logging
import time
from typing import Any, Awaitable, Callable

from everstaff.tools.feishu.auth_cards import build_auth_card, build_auth_success_card, build_auth_failed_card
from everstaff.tools.feishu.device_flow import request_device_authorization, poll_device_token
from everstaff.tools.feishu.errors import UserAuthRequiredError
from everstaff.tools.feishu.token_store import FileTokenStore, StoredToken
from everstaff.tools.feishu.uat_client import BASE_READONLY_SCOPES

logger = logging.getLogger(__name__)


async def handle_auth_error(
    *,
    err: UserAuthRequiredError,
    app_id: str,
    app_secret: str,
    domain: str = "feishu",
    send_card_fn: Callable[[dict], Awaitable[str]],
    update_card_fn: Callable[[str, dict], Awaitable[None]] | None = None,
    send_text_fn: Callable[[str], Awaitable[str]] | None = None,
    bot_name: str = "Agent",
    token_store: FileTokenStore | None = None,
    poll: bool = True,
    on_authorized: Callable[[], Awaitable[None]] | None = None,
) -> dict[str, Any]:
    """Handle a UserAuthRequiredError by initiating Device Flow.

    Sends an auth card, then blocks (up to 3 min) waiting for user to authorize.
    On success, stores the token and returns ``{"authorized": True}``.

    Args:
        err: The authorization error with user info and required scopes.
        app_id: Feishu app ID.
        app_secret: Feishu app secret.
        domain: 'feishu' or 'lark'.
        send_card_fn: async fn(card_dict) -> message_id. Sends card to user.
        update_card_fn: async fn(message_id, card_dict). Updates existing card.
        send_text_fn: async fn(text) -> message_id. Sends a text message to notify user.
        bot_name: Bot name for card header.
        token_store: Where to persist tokens.
        poll: Whether to poll for authorization (False for testing).
        on_authorized: Callback when authorization completes.

    Returns:
        dict with status info.
    """
    if token_store is None:
        raise ValueError("token_store is required")

    # Merge base read-only scopes with the tool's required scopes so the
    # user only needs to authorize once for common read operations.
    all_scopes = list(dict.fromkeys(BASE_READONLY_SCOPES + err.required_scopes))
    scope = " ".join(all_scopes)

    # 1. Request device authorization
    device_auth = await request_device_authorization(app_id, app_secret, scope=scope, domain=domain)

    # 2. Send auth card
    card = build_auth_card(
        verification_uri=device_auth["verification_uri_complete"],
        expires_min=max(1, device_auth["expires_in"] // 60),
        scopes=err.required_scopes,
        bot_name=bot_name,
    )
    message_id = await send_card_fn(card)

    # 2b. Send a text notification so the user knows the bot is waiting
    if send_text_fn:
        try:
            await send_text_fn("⏳ 需要您授权飞书权限后才能继续操作，请点击上方卡片中的链接完成授权。等待中...")
        except Exception as e:
            logger.warning("auto-auth: failed to send text notification: %s", e, exc_info=True)

    # 3. Poll for authorization (block until authorized or timeout)
    max_wait = min(device_auth["expires_in"], 180)  # cap at 3 minutes
    if poll:
        result = await poll_device_token(
            app_id=app_id, app_secret=app_secret,
            device_code=device_auth["device_code"],
            interval=device_auth["interval"],
            expires_in=max_wait, domain=domain,
        )

        if result["ok"]:
            now = int(time.time() * 1000)
            token = result["token"]
            await token_store.set(StoredToken(
                app_id=app_id,
                user_open_id=err.user_open_id,
                access_token=token["access_token"],
                refresh_token=token["refresh_token"],
                expires_at=now + token["expires_in"] * 1000,
                refresh_expires_at=now + token["refresh_expires_in"] * 1000,
                scope=token.get("scope", scope),
                granted_at=now,
            ))
            logger.info("auto-auth: user %s authorized successfully", err.user_open_id)

            if update_card_fn and message_id:
                try:
                    await update_card_fn(message_id, build_auth_success_card(bot_name=bot_name))
                except Exception as e:
                    logger.warning("auto-auth: failed to update card: %s", e, exc_info=True)

            if on_authorized:
                try:
                    await on_authorized()
                except Exception as e:
                    logger.warning("auto-auth: on_authorized callback failed: %s", e, exc_info=True)

            return {"authorized": True, "message": "✅ 授权成功"}
        else:
            if update_card_fn and message_id:
                try:
                    await update_card_fn(message_id, build_auth_failed_card(
                        reason=result.get("message", ""), bot_name=bot_name))
                except Exception as e:
                    logger.warning("auto-auth: failed to update card on failure: %s", e, exc_info=True)
            logger.warning("auto-auth: authorization failed for %s: %s", err.user_open_id, result.get("message"))
            return {
                "authorized": False,
                "message": f"❌ 授权失败: {result.get('message', '超时未授权')}",
            }

    return {
        "authorized": False,
        "message": "⏳ 需要用户授权飞书权限。授权卡片已发送到飞书。",
    }



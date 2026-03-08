"""Auto-auth middleware: intercepts tool auth errors and resolves via HITL cards.

When a Feishu tool call fails due to missing user authorization, this module:
1. Initiates OAuth Device Flow
2. Sends an auth card to the user via the Lark channel
3. Polls for token in background
4. Stores the token and signals completion
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable

from everstaff.feishu.auth_cards import build_auth_card, build_auth_success_card, build_auth_failed_card
from everstaff.feishu.device_flow import request_device_authorization, poll_device_token
from everstaff.feishu.errors import UserAuthRequiredError
from everstaff.feishu.token_store import FileTokenStore, StoredToken

logger = logging.getLogger(__name__)


async def handle_auth_error(
    *,
    err: UserAuthRequiredError,
    app_id: str,
    app_secret: str,
    domain: str = "feishu",
    send_card_fn: Callable[[dict], Awaitable[str]],
    update_card_fn: Callable[[str, dict], Awaitable[None]] | None = None,
    bot_name: str = "Agent",
    token_store: FileTokenStore | None = None,
    poll: bool = True,
    on_authorized: Callable[[], Awaitable[None]] | None = None,
) -> dict[str, Any]:
    """Handle a UserAuthRequiredError by initiating Device Flow.

    Args:
        err: The authorization error with user info and required scopes.
        app_id: Feishu app ID.
        app_secret: Feishu app secret.
        domain: 'feishu' or 'lark'.
        send_card_fn: async fn(card_dict) -> message_id. Sends card to user.
        update_card_fn: async fn(message_id, card_dict). Updates existing card.
        bot_name: Bot name for card header.
        token_store: Where to persist tokens.
        poll: Whether to start background polling (False for testing).
        on_authorized: Callback when authorization completes.

    Returns:
        dict with status info.
    """
    if token_store is None:
        raise ValueError("token_store is required")

    scope = " ".join(err.required_scopes)

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

    # 3. Start background polling
    if poll:
        asyncio.create_task(_poll_and_store(
            app_id=app_id,
            app_secret=app_secret,
            domain=domain,
            device_code=device_auth["device_code"],
            interval=device_auth["interval"],
            expires_in=device_auth["expires_in"],
            user_open_id=err.user_open_id,
            message_id=message_id,
            update_card_fn=update_card_fn,
            bot_name=bot_name,
            token_store=token_store,
            scope=scope,
            on_authorized=on_authorized,
        ))

    return {
        "awaiting_authorization": True,
        "message": "已发送授权请求卡片，请在卡片中点击链接完成授权。",
    }


async def _poll_and_store(
    *,
    app_id: str,
    app_secret: str,
    domain: str,
    device_code: str,
    interval: float,
    expires_in: int,
    user_open_id: str,
    message_id: str,
    update_card_fn: Callable | None,
    bot_name: str,
    token_store: FileTokenStore,
    scope: str,
    on_authorized: Callable | None,
) -> None:
    """Background task: poll for token, store it, update card."""
    try:
        result = await poll_device_token(
            app_id=app_id, app_secret=app_secret,
            device_code=device_code, interval=interval,
            expires_in=expires_in, domain=domain,
        )

        if result["ok"]:
            now = int(time.time() * 1000)
            token = result["token"]
            await token_store.set(StoredToken(
                app_id=app_id,
                user_open_id=user_open_id,
                access_token=token["access_token"],
                refresh_token=token["refresh_token"],
                expires_at=now + token["expires_in"] * 1000,
                refresh_expires_at=now + token["refresh_expires_in"] * 1000,
                scope=token.get("scope", scope),
                granted_at=now,
            ))

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

            logger.info("auto-auth: user %s authorized successfully", user_open_id)
        else:
            if update_card_fn and message_id:
                try:
                    await update_card_fn(message_id, build_auth_failed_card(
                        reason=result.get("message", ""), bot_name=bot_name))
                except Exception as e:
                    logger.warning("auto-auth: failed to update card on failure: %s", e, exc_info=True)
            logger.warning("auto-auth: authorization failed for %s: %s", user_open_id, result.get("message"))

    except Exception as e:
        logger.error("auto-auth: polling error for %s: %s", user_open_id, e, exc_info=True)

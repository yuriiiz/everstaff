"""UAT lifecycle management: refresh + retry."""
from __future__ import annotations

import logging
import time
from typing import Any, Callable, Awaitable

import httpx

from everstaff.feishu.device_flow import resolve_oauth_endpoints
from everstaff.feishu.token_store import FileTokenStore, StoredToken, token_status

logger = logging.getLogger(__name__)


class NeedAuthorizationError(Exception):
    """Raised when user needs to re-authorize (no valid token or refresh failed)."""
    def __init__(self, user_open_id: str) -> None:
        self.user_open_id = user_open_id
        super().__init__(f"User {user_open_id} needs authorization")


async def refresh_uat(
    app_id: str,
    app_secret: str,
    refresh_token: str,
    domain: str = "feishu",
) -> dict[str, Any]:
    """Refresh a user access token using the refresh token."""
    endpoints = resolve_oauth_endpoints(domain)
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            endpoints["token"],
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": app_id,
                "client_secret": app_secret,
            },
        )
    data = resp.json()
    if resp.status_code != 200 or "error" in data or not data.get("access_token"):
        msg = data.get("error_description") or data.get("error") or "refresh failed"
        raise RuntimeError(f"Token refresh failed: {msg}")
    return {
        "access_token": data["access_token"],
        "refresh_token": data.get("refresh_token", refresh_token),
        "expires_in": data.get("expires_in", 7200),
        "refresh_token_expires_in": data.get("refresh_token_expires_in", 604800),
    }


async def call_with_uat(
    *,
    user_open_id: str,
    app_id: str,
    app_secret: str,
    domain: str,
    fn: Callable[[str], Awaitable[Any]],
    token_store: FileTokenStore | None = None,
) -> Any:
    """Execute fn(access_token) with automatic token refresh.

    Raises NeedAuthorizationError if no stored token or refresh fails.
    """
    if token_store is None:
        token_store = FileTokenStore()

    stored = await token_store.get(app_id, user_open_id)
    if stored is None:
        raise NeedAuthorizationError(user_open_id)

    status = token_status(stored)

    if status == "expired":
        raise NeedAuthorizationError(user_open_id)

    if status == "needs_refresh":
        try:
            refreshed = await refresh_uat(app_id, app_secret, stored.refresh_token, domain)
            now = int(time.time() * 1000)
            stored = StoredToken(
                app_id=app_id,
                user_open_id=user_open_id,
                access_token=refreshed["access_token"],
                refresh_token=refreshed["refresh_token"],
                expires_at=now + refreshed["expires_in"] * 1000,
                refresh_expires_at=now + refreshed["refresh_token_expires_in"] * 1000,
                scope=stored.scope,
                granted_at=stored.granted_at,
            )
            await token_store.set(stored)
            logger.info("uat-client: refreshed token for %s", user_open_id)
        except Exception:
            logger.warning("uat-client: refresh failed for %s, re-auth required", user_open_id, exc_info=True)
            raise NeedAuthorizationError(user_open_id)

    return await fn(stored.access_token)

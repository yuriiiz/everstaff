"""OAuth 2.0 Device Authorization Grant (RFC 8628) for Feishu/Lark.

Ported from @larksuiteoapi/feishu-openclaw-plugin core/device-flow.js.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class DeviceFlowError(RuntimeError):
    """Raised when device authorization request fails."""


def resolve_oauth_endpoints(domain: str) -> dict[str, str]:
    """Resolve OAuth endpoint URLs based on domain (feishu or lark)."""
    if domain == "lark":
        return {
            "device_authorization": "https://accounts.larksuite.com/oauth/v1/device_authorization",
            "token": "https://open.larksuite.com/open-apis/authen/v2/oauth/token",
        }
    # Default: feishu
    return {
        "device_authorization": "https://accounts.feishu.cn/oauth/v1/device_authorization",
        "token": "https://open.feishu.cn/open-apis/authen/v2/oauth/token",
    }


async def request_device_authorization(
    app_id: str,
    app_secret: str,
    *,
    scope: str = "",
    domain: str = "feishu",
    include_offline_access: bool = True,
) -> dict[str, Any]:
    """Request a device authorization code from Feishu OAuth server.

    Returns dict with: device_code, user_code, verification_uri,
    verification_uri_complete, expires_in, interval.
    """
    endpoints = resolve_oauth_endpoints(domain)

    # Request offline_access for refresh token (configurable)
    if include_offline_access and "offline_access" not in scope:
        scope = f"{scope} offline_access".strip()

    basic_auth = base64.b64encode(f"{app_id}:{app_secret}".encode()).decode()

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            endpoints["device_authorization"],
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": f"Basic {basic_auth}",
            },
            data={"client_id": app_id, "scope": scope},
        )

    data = resp.json()
    if resp.status_code != 200 or "error" in data:
        msg = data.get("error_description") or data.get("error") or "Unknown error"
        raise DeviceFlowError(f"Device authorization failed: {msg}")

    logger.info("device-flow: device_code obtained, expires_in=%ds", data.get("expires_in", 240))

    return {
        "device_code": data["device_code"],
        "user_code": data.get("user_code", ""),
        "verification_uri": data.get("verification_uri", ""),
        "verification_uri_complete": data.get("verification_uri_complete", data.get("verification_uri", "")),
        "expires_in": data.get("expires_in", 240),
        "interval": data.get("interval", 5),
    }


async def poll_device_token(
    *,
    app_id: str,
    app_secret: str,
    device_code: str,
    interval: float,
    expires_in: int,
    domain: str = "feishu",
    cancel_event: asyncio.Event | None = None,
) -> dict[str, Any]:
    """Poll the token endpoint until user authorizes, rejects, or code expires.

    Returns: {"ok": True, "token": {...}} or {"ok": False, "error": "...", "message": "..."}
    """
    endpoints = resolve_oauth_endpoints(domain)
    deadline = time.monotonic() + expires_in

    async with httpx.AsyncClient() as client:
        while time.monotonic() < deadline:
            if cancel_event and cancel_event.is_set():
                return {"ok": False, "error": "cancelled", "message": "Polling was cancelled"}

            await asyncio.sleep(interval)

            try:
                resp = await client.post(
                    endpoints["token"],
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    data={
                        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                        "device_code": device_code,
                        "client_id": app_id,
                        "client_secret": app_secret,
                    },
                )
                data = resp.json()
            except Exception as e:
                logger.warning("device-flow: poll network error: %s", e, exc_info=True)
                continue

            error = data.get("error")

            if not error and data.get("access_token"):
                logger.info("device-flow: token obtained successfully")
                return {
                    "ok": True,
                    "token": {
                        "access_token": data["access_token"],
                        "refresh_token": data.get("refresh_token", ""),
                        "expires_in": data.get("expires_in", 7200),
                        "refresh_expires_in": data.get("refresh_token_expires_in", 604800),
                        "scope": data.get("scope", ""),
                    },
                }

            if error == "authorization_pending":
                continue
            if error == "slow_down":
                interval += 5
                logger.info("device-flow: slow_down, interval increased to %ss", interval)
                continue
            if error == "access_denied":
                return {"ok": False, "error": "access_denied", "message": "用户拒绝了授权"}
            if error in ("expired_token", "invalid_grant"):
                return {"ok": False, "error": "expired_token", "message": "授权码已过期，请重新发起"}

            desc = data.get("error_description") or error or "Unknown error"
            return {"ok": False, "error": error or "unknown_error", "message": desc}

        return {"ok": False, "error": "expired_token", "message": "授权超时，请重新发起"}

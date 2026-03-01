"""Auth routes for OIDC Authorization Code Flow."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from everstaff.api.auth.providers.oidc_code import OIDCCodeFlowProvider

logger = logging.getLogger(__name__)

_STATE_COOKIE = "oauth_state"


def make_auth_router(provider: OIDCCodeFlowProvider) -> APIRouter:
    """Build and return the auth APIRouter bound to *provider*."""
    router = APIRouter()

    @router.get("/auth/login")
    async def login(request: Request):
        """Start the OIDC Authorization Code Flow."""
        state = OIDCCodeFlowProvider.generate_state()
        auth_url = await provider.build_authorization_url(state)

        response = RedirectResponse(url=auth_url, status_code=302)
        response.set_cookie(
            key=_STATE_COOKIE,
            value=state,
            httponly=True,
            samesite="lax",
            secure=True,
            max_age=600,  # 10 minutes — enough to complete the flow
        )
        return response

    @router.get("/auth/callback")
    async def callback(request: Request, code: str | None = None, state: str | None = None):
        """Exchange the authorization code for a session cookie."""
        if not code:
            raise HTTPException(status_code=400, detail="Missing 'code' parameter")
        if not state:
            raise HTTPException(status_code=400, detail="Missing 'state' parameter")

        stored_state = request.cookies.get(_STATE_COOKIE)
        if not stored_state or stored_state != state:
            raise HTTPException(status_code=400, detail="Invalid state — possible CSRF")

        try:
            identity = await provider.exchange_code(code)
        except ValueError as exc:
            logger.warning("OIDC code exchange failed: %s", exc)
            raise HTTPException(status_code=400, detail=str(exc))

        session_jwt = provider.make_session_cookie(identity)
        cfg = provider._config

        response = RedirectResponse(url="/", status_code=302)
        response.set_cookie(
            key=cfg.cookie_name,
            value=session_jwt,
            httponly=True,
            samesite="lax",
            secure=True,
            max_age=cfg.cookie_max_age,
        )
        # Clear the state cookie
        response.delete_cookie(key=_STATE_COOKIE)
        return response

    @router.get("/auth/logout")
    async def logout(request: Request):
        """Clear the session cookie and redirect to home."""
        response = RedirectResponse(url="/", status_code=302)
        response.delete_cookie(
            key=provider.cookie_name,
            httponly=True,
            samesite="lax",
            secure=True,
        )
        return response

    return router

"""Tests for OIDC auth routes: /auth/login, /auth/callback, /auth/logout."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch

import jwt as pyjwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from everstaff.api.auth.models import AuthConfig, OIDCCodeFlowProviderConfig
from everstaff.api.auth.providers.oidc_code import OIDCCodeFlowProvider

_SECRET = "a-32-byte-secret-for-hs256-signing!"
_COOKIE_NAME = "agent_session"
_STATE_COOKIE = "oauth_state"


def _make_config() -> OIDCCodeFlowProviderConfig:
    return OIDCCodeFlowProviderConfig(
        issuer="https://idp.example.com",
        client_id="cid",
        client_secret="csec",
        redirect_uri="https://app.example.com/auth/callback",
        cookie_secret=_SECRET,
        cookie_name=_COOKIE_NAME,
    )


def _make_app() -> TestClient:
    """Build a minimal FastAPI app with auth router mounted."""
    from everstaff.api.auth.router import make_auth_router

    provider = OIDCCodeFlowProvider(_make_config())
    app = FastAPI()
    app.include_router(make_auth_router(provider))
    return TestClient(app, raise_server_exceptions=False, follow_redirects=False)


class TestLoginRoute:
    def test_login_redirects_to_oidc(self):
        client = _make_app()
        with patch.object(
            OIDCCodeFlowProvider,
            "build_authorization_url",
            new=AsyncMock(return_value="https://idp.example.com/auth?state=abc"),
        ):
            resp = client.get("/auth/login")

        assert resp.status_code == 302
        assert resp.headers["location"].startswith("https://idp.example.com/auth")

    def test_login_sets_state_cookie(self):
        client = _make_app()
        with patch.object(
            OIDCCodeFlowProvider,
            "build_authorization_url",
            new=AsyncMock(return_value="https://idp.example.com/auth?state=xyz"),
        ):
            resp = client.get("/auth/login")

        assert _STATE_COOKIE in resp.cookies


class TestCallbackRoute:
    def test_callback_sets_session_cookie_and_redirects(self):
        from everstaff.api.auth.models import UserIdentity

        client = _make_app()
        identity = UserIdentity(
            user_id="u1", email="u@e.com", name="User", provider="oidc_code"
        )
        state_value = "test-state-xyz"

        with patch.object(
            OIDCCodeFlowProvider,
            "exchange_code",
            new=AsyncMock(return_value=identity),
        ):
            resp = client.get(
                "/auth/callback",
                params={"code": "auth-code", "state": state_value},
                cookies={_STATE_COOKIE: state_value},
            )

        assert resp.status_code == 302
        assert resp.headers["location"] == "/"
        assert _COOKIE_NAME in resp.cookies
        assert _STATE_COOKIE not in resp.cookies  # state cookie must be cleared

    def test_callback_missing_state_returns_400(self):
        client = _make_app()
        resp = client.get(
            "/auth/callback",
            params={"code": "auth-code", "state": "some-state"},
            # No state cookie provided
        )
        assert resp.status_code == 400

    def test_callback_state_mismatch_returns_400(self):
        client = _make_app()
        resp = client.get(
            "/auth/callback",
            params={"code": "auth-code", "state": "state-A"},
            cookies={_STATE_COOKIE: "state-B"},
        )
        assert resp.status_code == 400

    def test_callback_exchange_failure_returns_400(self):
        client = _make_app()
        state_value = "test-state"
        with patch.object(
            OIDCCodeFlowProvider,
            "exchange_code",
            new=AsyncMock(side_effect=ValueError("token exchange failed")),
        ):
            resp = client.get(
                "/auth/callback",
                params={"code": "bad-code", "state": state_value},
                cookies={_STATE_COOKIE: state_value},
            )
        assert resp.status_code == 400

    def test_callback_missing_code_returns_400(self):
        client = _make_app()
        state_value = "test-state"
        resp = client.get(
            "/auth/callback",
            params={"state": state_value},
            cookies={_STATE_COOKIE: state_value},
        )
        assert resp.status_code == 400


class TestLogoutRoute:
    def test_logout_clears_cookie_and_redirects(self):
        client = _make_app()
        resp = client.get("/auth/logout")
        assert resp.status_code == 302
        assert resp.headers["location"] == "/"
        # Verify the session cookie is cleared (Max-Age=0 means deletion)
        set_cookie = resp.headers.get("set-cookie", "")
        assert _COOKIE_NAME in set_cookie
        assert "max-age=0" in set_cookie.lower()

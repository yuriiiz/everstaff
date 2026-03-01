"""End-to-end integration tests for API auth — middleware + WebSocket auth.

Uses ``create_app`` from ``everstaff.api`` with a custom ``FrameworkConfig``
so that the full middleware stack (including ``AuthMiddleware``) is wired up
exactly as it would be in production.
"""

from __future__ import annotations

import time

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient

from everstaff.api import create_app
from everstaff.api.auth.models import (
    AuthConfig,
    JWTProviderConfig,
    ProxyProviderConfig,
)
from everstaff.core.config import FrameworkConfig

# Suppress PyJWT warning for intentionally short test secrets.
pytestmark = pytest.mark.filterwarnings("ignore::jwt.InsecureKeyLengthWarning")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TEST_SECRET = "super-secret-key-for-testing!XYZ"  # 32 bytes — satisfies HS256


def _jwt_token(
    payload: dict | None = None,
    secret: str = _TEST_SECRET,
    algorithm: str = "HS256",
) -> str:
    """Create a signed JWT for test use."""
    if payload is None:
        payload = {
            "sub": "user-42",
            "name": "Alice",
            "email": "alice@example.com",
            "exp": int(time.time()) + 3600,
        }
    return pyjwt.encode(payload, secret, algorithm=algorithm)


def _make_config(
    tmp_path,
    *,
    auth: AuthConfig | None = None,
) -> FrameworkConfig:
    """Build a minimal ``FrameworkConfig`` pointing at *tmp_path*."""
    sessions_dir = str(tmp_path / "sessions")
    agents_dir = str(tmp_path / "agents")
    return FrameworkConfig(
        sessions_dir=sessions_dir,
        agents_dir=agents_dir,
        channels={},
        tracers=[],
        auth=auth,
    )


def _build_client(tmp_path, *, auth: AuthConfig | None = None) -> TestClient:
    """Create a ``TestClient`` backed by a fully-wired ``create_app`` instance."""
    config = _make_config(tmp_path, auth=auth)
    app = create_app(config, sessions_dir=config.sessions_dir)
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# 1. No auth config — all routes open
# ---------------------------------------------------------------------------


class TestNoAuthConfig:
    def test_no_auth_config_all_routes_open(self, tmp_path):
        """When ``auth`` is *None* in the config, no middleware is added and
        every route should be accessible without credentials."""
        client = _build_client(tmp_path, auth=None)

        resp_ping = client.get("/api/ping")
        assert resp_ping.status_code == 200

        resp_sessions = client.get("/api/sessions")
        assert resp_sessions.status_code == 200


# ---------------------------------------------------------------------------
# 2. Auth enabled — public route passes without token
# ---------------------------------------------------------------------------


class TestPublicRoutePassesWithAuth:
    def test_auth_enabled_public_route_passes(self, tmp_path):
        """/ping is in the default ``public_routes`` list and must succeed
        even when auth is enabled and no token is provided."""
        auth = AuthConfig(
            enabled=True,
            providers=[JWTProviderConfig(secret=_TEST_SECRET)],
        )
        client = _build_client(tmp_path, auth=auth)

        resp = client.get("/api/ping")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# 3. Auth enabled — protected route returns 401 without token
# ---------------------------------------------------------------------------


class TestProtectedRoute401:
    def test_auth_enabled_protected_route_401(self, tmp_path):
        """/sessions is a protected route; accessing it without a token must
        produce a 401 response."""
        auth = AuthConfig(
            enabled=True,
            providers=[JWTProviderConfig(secret=_TEST_SECRET)],
        )
        client = _build_client(tmp_path, auth=auth)

        resp = client.get("/api/sessions")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 4. Auth enabled — protected route with valid JWT → 200
# ---------------------------------------------------------------------------


class TestProtectedRouteWithValidToken:
    def test_auth_enabled_protected_route_with_valid_token(self, tmp_path):
        """Sending a valid JWT in the configured header must grant access to
        a protected endpoint."""
        auth = AuthConfig(
            enabled=True,
            providers=[JWTProviderConfig(secret=_TEST_SECRET)],
        )
        client = _build_client(tmp_path, auth=auth)

        token = _jwt_token()
        resp = client.get("/api/sessions", headers={"X-Auth-Token": token})
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 5. Multi-provider priority
# ---------------------------------------------------------------------------


class TestMultiProviderPriority:
    def test_multi_provider_jwt_succeeds_when_proxy_does_not_apply(self, tmp_path):
        """When both proxy and JWT providers are configured, a request
        carrying only a JWT header should be authenticated by the JWT
        provider (proxy returns *None* because its header is absent)."""
        auth = AuthConfig(
            enabled=True,
            providers=[
                ProxyProviderConfig(
                    headers={"user_id": "X-Proxy-User"},
                ),
                JWTProviderConfig(secret=_TEST_SECRET),
            ],
        )
        client = _build_client(tmp_path, auth=auth)

        token = _jwt_token()
        resp = client.get("/api/sessions", headers={"X-Auth-Token": token})
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 6. WebSocket auth — no token → close 4001
# ---------------------------------------------------------------------------


class TestWebSocketAuthNoToken:
    def test_websocket_auth_no_token_closes(self, tmp_path):
        """Connecting to /ws without a token when auth is enabled should
        result in an immediate close with code **4001**."""
        auth = AuthConfig(
            enabled=True,
            providers=[JWTProviderConfig(secret=_TEST_SECRET)],
        )
        client = _build_client(tmp_path, auth=auth)

        with client.websocket_connect("/api/ws") as ws:
            msg = ws.receive()
            assert msg["type"] == "websocket.close"
            assert msg["code"] == 4001

    def test_websocket_auth_invalid_token_closes(self, tmp_path):
        """Connecting with an invalid/expired token should also close 4001."""
        auth = AuthConfig(
            enabled=True,
            providers=[JWTProviderConfig(secret=_TEST_SECRET)],
        )
        client = _build_client(tmp_path, auth=auth)

        with client.websocket_connect("/api/ws?token=bad.token.here") as ws:
            msg = ws.receive()
            assert msg["type"] == "websocket.close"
            assert msg["code"] == 4001


# ---------------------------------------------------------------------------
# 7. WebSocket auth — valid token → connection stays open
# ---------------------------------------------------------------------------


class TestWebSocketAuthValidToken:
    def test_websocket_auth_valid_token(self, tmp_path):
        """Connecting to /ws?token=<valid_jwt> when auth is enabled must
        keep the connection open (no immediate close)."""
        auth = AuthConfig(
            enabled=True,
            providers=[JWTProviderConfig(secret=_TEST_SECRET)],
        )
        client = _build_client(tmp_path, auth=auth)
        token = _jwt_token()

        with client.websocket_connect(f"/api/ws?token={token}") as ws:
            # Connection accepted and still alive — send a trivial message
            # and confirm no error.
            ws.send_text('{"type": "ping"}')
            # The server loop will silently ignore this unknown type,
            # but the connection should remain open (no WebSocketDisconnect).

    def test_websocket_no_auth_config_stays_open(self, tmp_path):
        """When auth is *not* configured, /ws should accept without a token."""
        client = _build_client(tmp_path, auth=None)

        with client.websocket_connect("/api/ws") as ws:
            ws.send_text('{"type": "ping"}')


# ---------------------------------------------------------------------------
# 8. Email whitelist — HTTP
# ---------------------------------------------------------------------------


class TestEmailWhitelistHTTP:
    def test_whitelist_allows_matching_email(self, tmp_path):
        """User whose email is in allowed_emails gets 200."""
        auth = AuthConfig(
            enabled=True,
            providers=[JWTProviderConfig(secret=_TEST_SECRET)],
            allowed_emails=["alice@example.com"],
        )
        client = _build_client(tmp_path, auth=auth)
        token = _jwt_token()  # default payload has email=alice@example.com
        resp = client.get("/api/sessions", headers={"X-Auth-Token": token})
        assert resp.status_code == 200

    def test_whitelist_rejects_non_matching_email(self, tmp_path):
        """User whose email is NOT in allowed_emails gets 403."""
        auth = AuthConfig(
            enabled=True,
            providers=[JWTProviderConfig(secret=_TEST_SECRET)],
            allowed_emails=["bob@example.com"],
        )
        client = _build_client(tmp_path, auth=auth)
        token = _jwt_token()  # alice@example.com — not in list
        resp = client.get("/api/sessions", headers={"X-Auth-Token": token})
        assert resp.status_code == 403

    def test_whitelist_case_insensitive(self, tmp_path):
        """Email matching is case-insensitive."""
        auth = AuthConfig(
            enabled=True,
            providers=[JWTProviderConfig(secret=_TEST_SECRET)],
            allowed_emails=["ALICE@EXAMPLE.COM"],
        )
        client = _build_client(tmp_path, auth=auth)
        token = _jwt_token()  # alice@example.com
        resp = client.get("/api/sessions", headers={"X-Auth-Token": token})
        assert resp.status_code == 200

    def test_empty_whitelist_allows_all(self, tmp_path):
        """Empty allowed_emails list means all authenticated users pass."""
        auth = AuthConfig(
            enabled=True,
            providers=[JWTProviderConfig(secret=_TEST_SECRET)],
            allowed_emails=[],
        )
        client = _build_client(tmp_path, auth=auth)
        token = _jwt_token()
        resp = client.get("/api/sessions", headers={"X-Auth-Token": token})
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 9. Email whitelist — WebSocket
# ---------------------------------------------------------------------------


class TestEmailWhitelistWebSocket:
    def test_ws_whitelist_allows_matching_email(self, tmp_path):
        """WS connection with whitelisted email stays open."""
        auth = AuthConfig(
            enabled=True,
            providers=[JWTProviderConfig(secret=_TEST_SECRET)],
            allowed_emails=["alice@example.com"],
        )
        client = _build_client(tmp_path, auth=auth)
        token = _jwt_token()

        with client.websocket_connect(f"/api/ws?token={token}") as ws:
            ws.send_text('{"type": "ping"}')

    def test_ws_whitelist_rejects_non_matching_email(self, tmp_path):
        """WS connection with non-whitelisted email is closed with 4003."""
        auth = AuthConfig(
            enabled=True,
            providers=[JWTProviderConfig(secret=_TEST_SECRET)],
            allowed_emails=["bob@example.com"],
        )
        client = _build_client(tmp_path, auth=auth)
        token = _jwt_token()  # alice@example.com

        with client.websocket_connect(f"/api/ws?token={token}") as ws:
            msg = ws.receive()
            assert msg["type"] == "websocket.close"
            assert msg["code"] == 4003


# ---------------------------------------------------------------------------
# 10. OIDC Code Flow — auth routes are public, cookie grants API access
# ---------------------------------------------------------------------------


class TestOIDCCodeFlowIntegration:
    def test_auth_routes_are_public(self, tmp_path):
        """/auth/login and /auth/logout must be accessible without credentials."""
        from everstaff.api.auth.models import AuthConfig, OIDCCodeFlowProviderConfig

        auth = AuthConfig(
            enabled=True,
            providers=[
                OIDCCodeFlowProviderConfig(
                    issuer="https://idp.example.com",
                    client_id="cid",
                    client_secret="csec",
                    redirect_uri="https://app.example.com/auth/callback",
                    cookie_secret="a-32-byte-secret-for-hs256-signing!",
                )
            ],
        )
        client = _build_client(tmp_path, auth=auth)

        # /auth/login should redirect (302), not 401
        resp = client.get("/auth/login", follow_redirects=False)
        # Will fail trying to reach the real OIDC provider, but must NOT be 401
        assert resp.status_code != 401

        # /auth/logout is also public
        resp_logout = client.get("/auth/logout", follow_redirects=False)
        assert resp_logout.status_code != 401

    def test_valid_session_cookie_grants_api_access(self, tmp_path):
        """A valid signed session cookie must grant access to protected endpoints."""
        import time
        import jwt as pyjwt
        from everstaff.api.auth.models import AuthConfig, OIDCCodeFlowProviderConfig

        _SECRET = "a-32-byte-secret-for-hs256-signing!"
        auth = AuthConfig(
            enabled=True,
            providers=[
                OIDCCodeFlowProviderConfig(
                    issuer="https://idp.example.com",
                    client_id="cid",
                    client_secret="csec",
                    redirect_uri="https://app.example.com/auth/callback",
                    cookie_secret=_SECRET,
                )
            ],
        )
        client = _build_client(tmp_path, auth=auth)

        # Build a valid session JWT
        payload = {
            "sub": "user-42",
            "email": "alice@example.com",
            "name": "Alice",
            "provider": "oidc_code",
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
        }
        token = pyjwt.encode(payload, _SECRET, algorithm="HS256")

        resp = client.get("/api/sessions", cookies={"agent_session": token})
        assert resp.status_code == 200

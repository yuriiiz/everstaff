"""Tests for AuthMiddleware and get_current_user dependency."""

from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from everstaff.api.auth.middleware import AuthMiddleware, get_current_user
from everstaff.api.auth.models import AuthConfig, JWTProviderConfig, UserIdentity
from everstaff.api.auth.providers import AuthProvider


# ---------------------------------------------------------------------------
# Helpers — stub providers
# ---------------------------------------------------------------------------


class _SuccessProvider(AuthProvider):
    """Always authenticates with a fixed identity."""

    def __init__(self, *, user_id: str = "user-1", name: str = "Alice") -> None:
        self._identity = UserIdentity(
            user_id=user_id, name=name, email=f"{user_id}@test.com", provider="stub"
        )

    async def authenticate(self, request: Request) -> UserIdentity | None:
        return self._identity


class _NoneProvider(AuthProvider):
    """Always returns None (credentials not applicable)."""

    async def authenticate(self, request: Request) -> UserIdentity | None:
        return None


class _ErrorProvider(AuthProvider):
    """Raises a non-HTTP exception on authenticate."""

    async def authenticate(self, request: Request) -> UserIdentity | None:
        raise RuntimeError("boom")


class _ForbiddenProvider(AuthProvider):
    """Raises HTTPException(403) like ProxyProvider does."""

    async def authenticate(self, request: Request) -> UserIdentity | None:
        raise HTTPException(status_code=403, detail="Request source not trusted")


# ---------------------------------------------------------------------------
# Helpers — testable middleware subclass
# ---------------------------------------------------------------------------


class _TestableAuthMiddleware(AuthMiddleware):
    """AuthMiddleware subclass that accepts pre-built providers directly."""

    _injected_providers: list[AuthProvider] | None = None

    @staticmethod
    def _build_providers(provider_configs: list) -> list[AuthProvider]:
        # If providers were injected via the class var, use those instead
        if _TestableAuthMiddleware._injected_providers is not None:
            return list(_TestableAuthMiddleware._injected_providers)
        return AuthMiddleware._build_providers(provider_configs)


# ---------------------------------------------------------------------------
# Helpers — build a test app
# ---------------------------------------------------------------------------


def _make_app(
    *,
    providers: list[AuthProvider] | None = None,
    public_routes: list[str] | None = None,
    allowed_emails: list[str] | None = None,
) -> TestClient:
    """Create a minimal FastAPI app with AuthMiddleware and return a TestClient.

    When *providers* is given, they are injected into a testable subclass
    of ``AuthMiddleware``, bypassing ``_build_providers``.
    """
    if public_routes is None:
        public_routes = ["/ping", "/public/*"]

    auth_config = AuthConfig(
        enabled=True,
        public_routes=public_routes,
        allowed_emails=allowed_emails or [],
    )
    app = FastAPI()

    if providers is not None:
        _TestableAuthMiddleware._injected_providers = providers
        app.add_middleware(_TestableAuthMiddleware, auth_config=auth_config)
    else:
        app.add_middleware(AuthMiddleware, auth_config=auth_config)

    # Routes ----------------------------------------------------------------

    @app.get("/ping")
    async def ping():
        return {"status": "ok"}

    @app.get("/public/info")
    async def public_info():
        return {"info": "public"}

    @app.get("/protected")
    async def protected(request: Request):
        user: UserIdentity = request.state.user
        return {"user_id": user.user_id, "name": user.name}

    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Public routes
# ---------------------------------------------------------------------------


class TestPublicRoutes:
    def test_exact_public_route_bypasses_auth(self):
        client = _make_app(providers=[])
        resp = client.get("/ping")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_wildcard_public_route_bypasses_auth(self):
        client = _make_app(providers=[])
        resp = client.get("/public/info")
        assert resp.status_code == 200
        assert resp.json() == {"info": "public"}


# ---------------------------------------------------------------------------
# Protected routes — no credentials
# ---------------------------------------------------------------------------


class TestProtectedNoCredentials:
    def test_returns_401_without_credentials(self):
        client = _make_app(providers=[_NoneProvider()])
        resp = client.get("/protected")
        assert resp.status_code == 401
        body = resp.json()
        assert body["error"] == "unauthorized"
        assert "No valid credentials" in body["detail"]


# ---------------------------------------------------------------------------
# Protected routes — valid provider
# ---------------------------------------------------------------------------


class TestProtectedWithValidProvider:
    def test_returns_200_and_sets_user(self):
        client = _make_app(providers=[_SuccessProvider()])
        resp = client.get("/protected")
        assert resp.status_code == 200
        body = resp.json()
        assert body["user_id"] == "user-1"
        assert body["name"] == "Alice"


# ---------------------------------------------------------------------------
# Multiple providers
# ---------------------------------------------------------------------------


class TestMultipleProviders:
    def test_first_returns_none_second_succeeds(self):
        client = _make_app(
            providers=[
                _NoneProvider(),
                _SuccessProvider(user_id="user-2", name="Bob"),
            ],
        )
        resp = client.get("/protected")
        assert resp.status_code == 200
        body = resp.json()
        assert body["user_id"] == "user-2"
        assert body["name"] == "Bob"


# ---------------------------------------------------------------------------
# Provider exceptions
# ---------------------------------------------------------------------------


class TestProviderExceptions:
    def test_generic_exception_logged_and_next_provider_tried(self):
        """Non-HTTP exceptions are caught; the next provider is tried."""
        client = _make_app(
            providers=[
                _ErrorProvider(),
                _SuccessProvider(user_id="user-3", name="Carol"),
            ],
        )
        resp = client.get("/protected")
        assert resp.status_code == 200
        body = resp.json()
        assert body["user_id"] == "user-3"

    def test_http_exception_is_reraised(self):
        """HTTPException (e.g. 403 from ProxyProvider) is not swallowed."""
        client = _make_app(
            providers=[
                _ForbiddenProvider(),
                _SuccessProvider(),  # should never be reached
            ],
        )
        resp = client.get("/protected")
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# get_current_user dependency
# ---------------------------------------------------------------------------


class TestGetCurrentUser:
    @pytest.mark.asyncio
    async def test_returns_user_when_present(self):
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "query_string": b"",
            "headers": [],
        }
        request = Request(scope)
        identity = UserIdentity(
            user_id="dep-user", name="Dep", email="dep@test.com", provider="test"
        )
        request.state.user = identity

        result = await get_current_user(request)
        assert result is identity
        assert result.user_id == "dep-user"

    @pytest.mark.asyncio
    async def test_raises_401_when_no_user(self):
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "query_string": b"",
            "headers": [],
        }
        request = Request(scope)
        # request.state.user is not set

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(request)
        assert exc_info.value.status_code == 401
        assert "Not authenticated" in str(exc_info.value.detail)


# ---------------------------------------------------------------------------
# _build_providers
# ---------------------------------------------------------------------------


class TestBuildProviders:
    def test_build_providers_jwt(self):
        """_build_providers correctly instantiates JWTProvider from config."""
        from everstaff.api.auth.providers.jwt import JWTProvider

        configs = [JWTProviderConfig(secret="test-secret-key-for-testing!X")]
        providers = AuthMiddleware._build_providers(configs)
        assert len(providers) == 1
        assert isinstance(providers[0], JWTProvider)

    def test_build_providers_oidc_code(self):
        """_build_providers correctly instantiates OIDCCodeFlowProvider from config."""
        from everstaff.api.auth.providers.oidc_code import OIDCCodeFlowProvider
        from everstaff.api.auth.models import OIDCCodeFlowProviderConfig

        configs = [OIDCCodeFlowProviderConfig(
            issuer="https://idp.example.com",
            client_id="cid",
            client_secret="csec",
            redirect_uri="https://app.example.com/auth/callback",
            cookie_secret="a-32-byte-secret-for-hs256-signing!",
        )]
        providers = AuthMiddleware._build_providers(configs)
        assert len(providers) == 1
        assert isinstance(providers[0], OIDCCodeFlowProvider)


# ---------------------------------------------------------------------------
# Email whitelist
# ---------------------------------------------------------------------------


class TestEmailWhitelist:
    def test_empty_whitelist_allows_all(self):
        """Empty allowed_emails list means all authenticated users pass."""
        client = _make_app(
            providers=[_SuccessProvider()],
            allowed_emails=[],
        )
        resp = client.get("/protected")
        assert resp.status_code == 200

    def test_whitelist_allows_matching_email(self):
        """User whose email is in the whitelist gets access."""
        client = _make_app(
            providers=[_SuccessProvider(user_id="user-1")],
            allowed_emails=["user-1@test.com"],
        )
        resp = client.get("/protected")
        assert resp.status_code == 200

    def test_whitelist_rejects_non_matching_email(self):
        """User whose email is NOT in the whitelist gets 403."""
        client = _make_app(
            providers=[_SuccessProvider(user_id="user-1")],
            allowed_emails=["other@test.com"],
        )
        resp = client.get("/protected")
        assert resp.status_code == 403
        body = resp.json()
        assert body["error"] == "forbidden"

    def test_whitelist_case_insensitive(self):
        """Email matching is case-insensitive."""
        client = _make_app(
            providers=[_SuccessProvider(user_id="user-1")],
            allowed_emails=["USER-1@TEST.COM"],
        )
        resp = client.get("/protected")
        assert resp.status_code == 200

    def test_whitelist_rejects_when_no_email(self):
        """User with no email is rejected when whitelist is active."""

        class _NoEmailProvider(AuthProvider):
            async def authenticate(self, request: Request) -> UserIdentity | None:
                return UserIdentity(
                    user_id="no-email-user", name="NoEmail", email=None, provider="stub"
                )

        client = _make_app(
            providers=[_NoEmailProvider()],
            allowed_emails=["someone@test.com"],
        )
        resp = client.get("/protected")
        assert resp.status_code == 403

    def test_whitelist_does_not_affect_public_routes(self):
        """Public routes bypass both auth and email whitelist."""
        client = _make_app(
            providers=[],
            allowed_emails=["someone@test.com"],
        )
        resp = client.get("/ping")
        assert resp.status_code == 200

"""Tests for the JWT authentication provider."""

from __future__ import annotations

import time

import jwt as pyjwt
import pytest
from starlette.requests import Request

from everstaff.api.auth.models import JWTProviderConfig
from everstaff.api.auth.providers.jwt import JWTProvider

# Suppress PyJWT warning for intentionally short test secrets (e.g. "wrong-secret").
pytestmark = pytest.mark.filterwarnings("ignore::jwt.InsecureKeyLengthWarning")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TEST_SECRET = "super-secret-key-for-testing!XYZ"  # 32 bytes (satisfies HS256 minimum)


def _make_request(headers: dict[str, str] | None = None) -> Request:
    """Build a minimal Starlette ``Request`` with the given headers."""
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "query_string": b"",
        "headers": [
            (k.lower().encode(), v.encode()) for k, v in (headers or {}).items()
        ],
    }
    return Request(scope)


def _encode_token(
    payload: dict,
    secret: str = _TEST_SECRET,
    algorithm: str = "HS256",
) -> str:
    """Create a JWT token for testing."""
    return pyjwt.encode(payload, secret, algorithm=algorithm)


def _default_payload(**overrides: object) -> dict:
    """Return a valid JWT payload with sensible defaults."""
    base = {
        "sub": "user-42",
        "name": "Alice",
        "email": "alice@example.com",
        "exp": int(time.time()) + 3600,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Auth success
# ---------------------------------------------------------------------------


class TestAuthSuccess:
    @pytest.mark.asyncio
    async def test_valid_hs256_token(self):
        config = JWTProviderConfig(secret=_TEST_SECRET)
        provider = JWTProvider(config)

        token = _encode_token(_default_payload())
        request = _make_request(headers={"X-Auth-Token": token})
        identity = await provider.authenticate(request)

        assert identity is not None
        assert identity.user_id == "user-42"
        assert identity.name == "Alice"
        assert identity.email == "alice@example.com"
        assert identity.provider == "jwt"


# ---------------------------------------------------------------------------
# Returns None when provider doesn't apply
# ---------------------------------------------------------------------------


class TestReturnsNone:
    @pytest.mark.asyncio
    async def test_header_missing(self):
        config = JWTProviderConfig(secret=_TEST_SECRET)
        provider = JWTProvider(config)

        request = _make_request(headers={})
        assert await provider.authenticate(request) is None

    @pytest.mark.asyncio
    async def test_header_empty(self):
        config = JWTProviderConfig(secret=_TEST_SECRET)
        provider = JWTProvider(config)

        request = _make_request(headers={"X-Auth-Token": ""})
        assert await provider.authenticate(request) is None

    @pytest.mark.asyncio
    async def test_token_expired(self):
        config = JWTProviderConfig(secret=_TEST_SECRET)
        provider = JWTProvider(config)

        token = _encode_token(_default_payload(exp=int(time.time()) - 10))
        request = _make_request(headers={"X-Auth-Token": token})
        assert await provider.authenticate(request) is None

    @pytest.mark.asyncio
    async def test_invalid_signature(self):
        config = JWTProviderConfig(secret=_TEST_SECRET)
        provider = JWTProvider(config)

        token = _encode_token(_default_payload(), secret="wrong-secret")
        request = _make_request(headers={"X-Auth-Token": token})
        assert await provider.authenticate(request) is None

    @pytest.mark.asyncio
    async def test_malformed_token(self):
        config = JWTProviderConfig(secret=_TEST_SECRET)
        provider = JWTProvider(config)

        request = _make_request(headers={"X-Auth-Token": "not.a.jwt"})
        assert await provider.authenticate(request) is None

    @pytest.mark.asyncio
    async def test_user_id_claim_missing(self):
        """When the payload has no ``sub`` claim, authenticate returns None."""
        config = JWTProviderConfig(secret=_TEST_SECRET)
        provider = JWTProvider(config)

        payload = _default_payload()
        del payload["sub"]
        token = _encode_token(payload)
        request = _make_request(headers={"X-Auth-Token": token})
        assert await provider.authenticate(request) is None


# ---------------------------------------------------------------------------
# Custom header and claims mapping
# ---------------------------------------------------------------------------


class TestCustomConfiguration:
    @pytest.mark.asyncio
    async def test_custom_header_name(self):
        config = JWTProviderConfig(secret=_TEST_SECRET, header="Authorization")
        provider = JWTProvider(config)

        token = _encode_token(_default_payload())
        request = _make_request(headers={"Authorization": token})
        identity = await provider.authenticate(request)

        assert identity is not None
        assert identity.user_id == "user-42"

    @pytest.mark.asyncio
    async def test_custom_claims_mapping(self):
        config = JWTProviderConfig(
            secret=_TEST_SECRET,
            claims_mapping={
                "user_id": "uid",
                "name": "display_name",
                "email": "mail",
            },
        )
        provider = JWTProvider(config)

        payload = {
            "uid": "custom-id",
            "display_name": "Bob",
            "mail": "bob@example.com",
            "exp": int(time.time()) + 3600,
        }
        token = _encode_token(payload)
        request = _make_request(headers={"X-Auth-Token": token})
        identity = await provider.authenticate(request)

        assert identity is not None
        assert identity.user_id == "custom-id"
        assert identity.name == "Bob"
        assert identity.email == "bob@example.com"


# ---------------------------------------------------------------------------
# Env var expansion
# ---------------------------------------------------------------------------


class TestEnvVarExpansion:
    @pytest.mark.asyncio
    async def test_secret_from_env_var(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("JWT_SECRET", _TEST_SECRET)

        config = JWTProviderConfig(secret="${JWT_SECRET}")
        provider = JWTProvider(config)

        token = _encode_token(_default_payload())
        request = _make_request(headers={"X-Auth-Token": token})
        identity = await provider.authenticate(request)

        assert identity is not None
        assert identity.user_id == "user-42"

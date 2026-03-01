"""Tests for the OIDC authentication provider."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from starlette.requests import Request

from everstaff.api.auth.models import OIDCProviderConfig
from everstaff.api.auth.providers.oidc import OIDCProvider


# ---------------------------------------------------------------------------
# RSA key helpers
# ---------------------------------------------------------------------------

def _generate_rsa_keypair() -> tuple[rsa.RSAPrivateKey, rsa.RSAPublicKey]:
    """Generate an RSA private/public key pair for testing."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


_PRIVATE_KEY, _PUBLIC_KEY = _generate_rsa_keypair()

_PRIVATE_PEM = _PRIVATE_KEY.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
)


# ---------------------------------------------------------------------------
# Request / token helpers
# ---------------------------------------------------------------------------

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


def _default_payload(**overrides: object) -> dict:
    """Return a valid JWT payload with sensible defaults."""
    base = {
        "sub": "user-42",
        "name": "Alice",
        "email": "alice@example.com",
        "iss": "https://idp.example.com",
        "exp": int(time.time()) + 3600,
    }
    base.update(overrides)
    return base


_TEST_KID = "test-key-1"


def _encode_rs256_token(payload: dict, private_key_pem: bytes = _PRIVATE_PEM) -> str:
    """Sign a JWT with RS256 using the test private key (includes ``kid`` header)."""
    return pyjwt.encode(
        payload, private_key_pem, algorithm="RS256", headers={"kid": _TEST_KID}
    )


def _make_jwks_client_from_public_key(
    public_key: rsa.RSAPublicKey,
) -> pyjwt.PyJWKClient:
    """Create a real ``PyJWKClient`` backed by the test public key.

    We build a JWKS JSON structure from the public key and feed it into a
    ``PyJWKClient`` instance whose ``get_jwk_set`` is overridden so it
    never makes network calls.
    """
    jwk_dict = pyjwt.algorithms.RSAAlgorithm.to_jwk(public_key, as_dict=True)
    jwk_dict["kid"] = _TEST_KID
    jwk_dict["use"] = "sig"
    jwk_dict["alg"] = "RS256"

    jwks_data = {"keys": [jwk_dict]}
    jwk_set = pyjwt.PyJWKSet.from_dict(jwks_data)

    client = pyjwt.PyJWKClient("https://idp.example.com/.well-known/jwks.json")
    client.get_jwk_set = lambda *_a, **_kw: jwk_set  # type: ignore[assignment]
    return client


_TEST_JWKS_CLIENT = _make_jwks_client_from_public_key(_PUBLIC_KEY)


def _make_provider(
    *,
    issuer: str = "https://idp.example.com",
    audience: str | None = None,
    claims_mapping: dict[str, str] | None = None,
    inject_jwks_client: bool = True,
) -> OIDCProvider:
    """Create an ``OIDCProvider`` with the JWKS client already injected."""
    config_kwargs: dict = {"issuer": issuer}
    if audience is not None:
        config_kwargs["audience"] = audience
    if claims_mapping is not None:
        config_kwargs["claims_mapping"] = claims_mapping

    config = OIDCProviderConfig(**config_kwargs)
    provider = OIDCProvider(config)
    if inject_jwks_client:
        provider._jwks_client = _TEST_JWKS_CLIENT
    return provider


# ---------------------------------------------------------------------------
# Auth success
# ---------------------------------------------------------------------------


class TestAuthSuccess:
    @pytest.mark.asyncio
    async def test_valid_rs256_token(self):
        provider = _make_provider()
        token = _encode_rs256_token(_default_payload())
        request = _make_request(headers={"Authorization": f"Bearer {token}"})

        identity = await provider.authenticate(request)

        assert identity is not None
        assert identity.user_id == "user-42"
        assert identity.name == "Alice"
        assert identity.email == "alice@example.com"
        assert identity.provider == "oidc"

    @pytest.mark.asyncio
    async def test_custom_claims_mapping(self):
        provider = _make_provider(
            claims_mapping={
                "user_id": "uid",
                "name": "display_name",
                "email": "mail",
            },
        )
        payload = _default_payload(uid="custom-id", display_name="Bob", mail="bob@example.com")
        # Remove default claim keys so they don't interfere
        del payload["sub"]
        del payload["name"]
        del payload["email"]
        token = _encode_rs256_token(payload)
        request = _make_request(headers={"Authorization": f"Bearer {token}"})

        identity = await provider.authenticate(request)

        assert identity is not None
        assert identity.user_id == "custom-id"
        assert identity.name == "Bob"
        assert identity.email == "bob@example.com"


# ---------------------------------------------------------------------------
# Returns None when provider doesn't apply
# ---------------------------------------------------------------------------


class TestReturnsNone:
    @pytest.mark.asyncio
    async def test_no_authorization_header(self):
        provider = _make_provider()
        request = _make_request(headers={})
        assert await provider.authenticate(request) is None

    @pytest.mark.asyncio
    async def test_authorization_not_bearer(self):
        provider = _make_provider()
        request = _make_request(headers={"Authorization": "Basic dXNlcjpwYXNz"})
        assert await provider.authenticate(request) is None

    @pytest.mark.asyncio
    async def test_bearer_token_empty(self):
        provider = _make_provider()
        request = _make_request(headers={"Authorization": "Bearer "})
        assert await provider.authenticate(request) is None

    @pytest.mark.asyncio
    async def test_expired_token(self):
        provider = _make_provider()
        token = _encode_rs256_token(_default_payload(exp=int(time.time()) - 10))
        request = _make_request(headers={"Authorization": f"Bearer {token}"})
        assert await provider.authenticate(request) is None

    @pytest.mark.asyncio
    async def test_user_id_claim_missing(self):
        """When the payload has no ``sub`` claim, authenticate returns None."""
        provider = _make_provider()
        payload = _default_payload()
        del payload["sub"]
        token = _encode_rs256_token(payload)
        request = _make_request(headers={"Authorization": f"Bearer {token}"})
        assert await provider.authenticate(request) is None

    @pytest.mark.asyncio
    async def test_malformed_token(self):
        provider = _make_provider()
        request = _make_request(headers={"Authorization": "Bearer not.a.jwt"})
        assert await provider.authenticate(request) is None


# ---------------------------------------------------------------------------
# OIDC discovery
# ---------------------------------------------------------------------------


class TestDiscovery:
    @pytest.mark.asyncio
    async def test_discovery_failure_marks_unavailable(self):
        """When OIDC discovery fails, the provider logs a warning and returns None."""
        provider = _make_provider(inject_jwks_client=False)

        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = Exception("connection refused")

        # session.get() returns a sync context-manager-like object that
        # supports ``async with`` (i.e. has __aenter__/__aexit__).
        mock_get_ctx = MagicMock()
        mock_get_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_get_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.get.return_value = mock_get_ctx

        # ClientSession() itself is used as ``async with``.
        mock_session_cls = MagicMock()
        mock_session_cls.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cls.__aexit__ = AsyncMock(return_value=False)

        with patch("everstaff.api.auth.providers.oidc.aiohttp.ClientSession", return_value=mock_session_cls):
            token = _encode_rs256_token(_default_payload())
            request = _make_request(headers={"Authorization": f"Bearer {token}"})

            result = await provider.authenticate(request)

        assert result is None
        assert provider._available is False

    @pytest.mark.asyncio
    async def test_unavailable_provider_returns_none_without_retry(self):
        """Once marked unavailable, _ensure_jwks_client returns None immediately."""
        provider = _make_provider(inject_jwks_client=False)
        provider._available = False

        token = _encode_rs256_token(_default_payload())
        request = _make_request(headers={"Authorization": f"Bearer {token}"})
        assert await provider.authenticate(request) is None

    @pytest.mark.asyncio
    async def test_discovery_cached_across_requests(self):
        """The JWKS client should be initialised only once across multiple calls."""
        provider = _make_provider(inject_jwks_client=False)

        original_ensure = OIDCProvider._ensure_jwks_client

        async def _tracked_ensure(self: OIDCProvider) -> pyjwt.PyJWKClient | None:
            """Wrap the real method but inject the test client on first call."""
            if self._jwks_client is not None:
                return self._jwks_client
            _tracked_ensure.call_count += 1  # type: ignore[attr-defined]
            self._jwks_client = _TEST_JWKS_CLIENT
            return _TEST_JWKS_CLIENT

        _tracked_ensure.call_count = 0  # type: ignore[attr-defined]

        with patch.object(OIDCProvider, "_ensure_jwks_client", _tracked_ensure):
            token = _encode_rs256_token(_default_payload())
            request = _make_request(headers={"Authorization": f"Bearer {token}"})

            # First request triggers discovery (tracked call).
            await provider.authenticate(request)
            # Second request uses the cached client.
            await provider.authenticate(request)

        assert _tracked_ensure.call_count == 1  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Audience verification
# ---------------------------------------------------------------------------


class TestAudienceVerification:
    @pytest.mark.asyncio
    async def test_audience_mismatch_returns_none(self):
        """Token with wrong audience should fail validation."""
        provider = _make_provider(audience="expected-audience")
        token = _encode_rs256_token(_default_payload(aud="wrong-audience"))
        request = _make_request(headers={"Authorization": f"Bearer {token}"})
        assert await provider.authenticate(request) is None

    @pytest.mark.asyncio
    async def test_audience_match_succeeds(self):
        """Token with correct audience should pass validation."""
        provider = _make_provider(audience="expected-audience")
        token = _encode_rs256_token(_default_payload(aud="expected-audience"))
        request = _make_request(headers={"Authorization": f"Bearer {token}"})

        identity = await provider.authenticate(request)

        assert identity is not None
        assert identity.user_id == "user-42"

    @pytest.mark.asyncio
    async def test_no_audience_config_skips_verification(self):
        """When no audience is configured, tokens without aud are accepted."""
        provider = _make_provider(audience=None)
        # Token has no aud claim — should still work when audience is not configured.
        token = _encode_rs256_token(_default_payload())
        request = _make_request(headers={"Authorization": f"Bearer {token}"})

        identity = await provider.authenticate(request)

        assert identity is not None
        assert identity.user_id == "user-42"

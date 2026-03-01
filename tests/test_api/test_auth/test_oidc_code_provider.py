"""Tests for OIDCCodeFlowProvider.authenticate() — cookie validation."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import jwt as pyjwt
import pytest
from starlette.requests import Request

from everstaff.api.auth.models import OIDCCodeFlowProviderConfig
from everstaff.api.auth.providers.oidc_code import OIDCCodeFlowProvider

_SECRET = "a-32-byte-secret-for-hs256-signing!"
_COOKIE_NAME = "agent_session"


def _make_config(**overrides) -> OIDCCodeFlowProviderConfig:
    base = dict(
        issuer="https://idp.example.com",
        client_id="cid",
        client_secret="csec",
        redirect_uri="https://app.example.com/auth/callback",
        cookie_secret=_SECRET,
        cookie_name=_COOKIE_NAME,
    )
    base.update(overrides)
    return OIDCCodeFlowProviderConfig(**base)


def _make_request(cookies: dict[str, str] | None = None) -> Request:
    """Build a minimal Starlette Request with the given cookies."""
    cookie_header = "; ".join(f"{k}={v}" for k, v in (cookies or {}).items())
    headers = [(b"cookie", cookie_header.encode())] if cookie_header else []
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/sessions",
        "query_string": b"",
        "headers": headers,
    }
    return Request(scope)


def _make_session_jwt(payload_overrides: dict | None = None) -> str:
    payload = {
        "sub": "user-42",
        "email": "alice@example.com",
        "name": "Alice",
        "provider": "oidc_code",
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
    }
    if payload_overrides:
        payload.update(payload_overrides)
    return pyjwt.encode(payload, _SECRET, algorithm="HS256")


class TestAuthenticate:
    @pytest.mark.asyncio
    async def test_valid_cookie_returns_identity(self):
        provider = OIDCCodeFlowProvider(_make_config())
        token = _make_session_jwt()
        request = _make_request(cookies={_COOKIE_NAME: token})

        identity = await provider.authenticate(request)

        assert identity is not None
        assert identity.user_id == "user-42"
        assert identity.email == "alice@example.com"
        assert identity.name == "Alice"
        assert identity.provider == "oidc_code"

    @pytest.mark.asyncio
    async def test_no_cookie_returns_none(self):
        provider = OIDCCodeFlowProvider(_make_config())
        request = _make_request(cookies={})
        assert await provider.authenticate(request) is None

    @pytest.mark.asyncio
    async def test_wrong_cookie_name_returns_none(self):
        provider = OIDCCodeFlowProvider(_make_config())
        token = _make_session_jwt()
        request = _make_request(cookies={"other_cookie": token})
        assert await provider.authenticate(request) is None

    @pytest.mark.asyncio
    async def test_expired_cookie_returns_none(self):
        provider = OIDCCodeFlowProvider(_make_config())
        token = _make_session_jwt({"exp": int(time.time()) - 10})
        request = _make_request(cookies={_COOKIE_NAME: token})
        assert await provider.authenticate(request) is None

    @pytest.mark.asyncio
    async def test_tampered_cookie_returns_none(self):
        provider = OIDCCodeFlowProvider(_make_config())
        # Sign with a different secret
        token = pyjwt.encode(
            {"sub": "hacker", "exp": int(time.time()) + 3600},
            "wrong-secret",
            algorithm="HS256",
        )
        request = _make_request(cookies={_COOKIE_NAME: token})
        assert await provider.authenticate(request) is None

    @pytest.mark.asyncio
    async def test_malformed_cookie_returns_none(self):
        provider = OIDCCodeFlowProvider(_make_config())
        request = _make_request(cookies={_COOKIE_NAME: "not.a.jwt"})
        assert await provider.authenticate(request) is None

    @pytest.mark.asyncio
    async def test_missing_sub_claim_returns_none(self):
        provider = OIDCCodeFlowProvider(_make_config())
        token = _make_session_jwt({"sub": None})
        # Re-encode without sub
        payload = {
            "email": "alice@example.com",
            "name": "Alice",
            "provider": "oidc_code",
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
        }
        token = pyjwt.encode(payload, _SECRET, algorithm="HS256")
        request = _make_request(cookies={_COOKIE_NAME: token})
        assert await provider.authenticate(request) is None


class TestMakeSessionCookie:
    def test_roundtrip(self):
        """make_session_cookie() produces a JWT that authenticate() can validate."""
        from everstaff.api.auth.models import UserIdentity

        provider = OIDCCodeFlowProvider(_make_config())
        identity = UserIdentity(
            user_id="u1", email="u@e.com", name="U", provider="oidc_code"
        )
        cookie_value = provider.make_session_cookie(identity)
        decoded = pyjwt.decode(cookie_value, _SECRET, algorithms=["HS256"])
        assert decoded["sub"] == "u1"
        assert decoded["email"] == "u@e.com"
        assert decoded["name"] == "U"
        assert decoded["provider"] == "oidc_code"
        assert "exp" in decoded
        assert "iat" in decoded


class TestExchangeCode:
    @pytest.mark.asyncio
    async def test_exchange_code_returns_identity(self):
        """exchange_code() returns a UserIdentity on success."""
        import time as _time

        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        # Generate RSA keypair for id_token signing
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )

        id_token_payload = {
            "sub": "user-99",
            "email": "bob@example.com",
            "name": "Bob",
            "iat": int(_time.time()),
            "exp": int(_time.time()) + 3600,
        }
        id_token = pyjwt.encode(
            id_token_payload,
            private_pem,
            algorithm="RS256",
            headers={"kid": "test-kid"},
        )

        # Build a JWKS client backed by the test public key
        public_key = private_key.public_key()
        jwk_dict = pyjwt.algorithms.RSAAlgorithm.to_jwk(public_key, as_dict=True)
        jwk_dict["kid"] = "test-kid"
        jwk_dict["use"] = "sig"
        jwk_dict["alg"] = "RS256"
        jwks_data = {"keys": [jwk_dict]}
        jwk_set = pyjwt.PyJWKSet.from_dict(jwks_data)

        # Create a real JWKS client but override its fetcher
        jwks_client = pyjwt.PyJWKClient("https://idp.example.com/.well-known/jwks.json")
        jwks_client.get_jwk_set = lambda *_a, **_kw: jwk_set

        provider = OIDCCodeFlowProvider(_make_config())
        provider._jwks_client = jwks_client

        # Mock the token endpoint
        mock_tokens = {"id_token": id_token, "access_token": "at"}
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value=mock_tokens)
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_post_ctx = MagicMock()
        mock_post_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_post_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.post.return_value = mock_post_ctx

        mock_session_cls = MagicMock()
        mock_session_cls.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cls.__aexit__ = AsyncMock(return_value=False)

        # Mock _discover to return a fake discovery doc
        discovery_doc = {
            "authorization_endpoint": "https://idp.example.com/auth",
            "token_endpoint": "https://idp.example.com/token",
            "jwks_uri": "https://idp.example.com/.well-known/jwks.json",
        }
        with patch.object(provider, "_discover", new=AsyncMock(return_value=discovery_doc)):
            with patch("everstaff.api.auth.providers.oidc_code.aiohttp.ClientSession", return_value=mock_session_cls):
                identity = await provider.exchange_code("my-auth-code")

        assert identity.user_id == "user-99"
        assert identity.email == "bob@example.com"
        assert identity.name == "Bob"
        assert identity.provider == "oidc_code"

    @pytest.mark.asyncio
    async def test_exchange_code_raises_on_token_endpoint_error(self):
        """exchange_code() raises ValueError when token endpoint returns non-200."""
        provider = OIDCCodeFlowProvider(_make_config())

        mock_resp = MagicMock()
        mock_resp.status = 400
        mock_resp.text = AsyncMock(return_value="invalid_grant")
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_post_ctx = MagicMock()
        mock_post_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_post_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.post.return_value = mock_post_ctx

        mock_session_cls = MagicMock()
        mock_session_cls.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cls.__aexit__ = AsyncMock(return_value=False)

        discovery_doc = {
            "authorization_endpoint": "https://idp.example.com/auth",
            "token_endpoint": "https://idp.example.com/token",
            "jwks_uri": "https://idp.example.com/.well-known/jwks.json",
        }
        with patch.object(provider, "_discover", new=AsyncMock(return_value=discovery_doc)):
            with patch("everstaff.api.auth.providers.oidc_code.aiohttp.ClientSession", return_value=mock_session_cls):
                with pytest.raises(ValueError, match="Token exchange failed"):
                    await provider.exchange_code("bad-code")

    @pytest.mark.asyncio
    async def test_exchange_code_raises_when_no_id_token(self):
        """exchange_code() raises ValueError when id_token is absent from response."""
        provider = OIDCCodeFlowProvider(_make_config())

        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"access_token": "at"})  # no id_token
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_post_ctx = MagicMock()
        mock_post_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_post_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.post.return_value = mock_post_ctx

        mock_session_cls = MagicMock()
        mock_session_cls.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cls.__aexit__ = AsyncMock(return_value=False)

        discovery_doc = {
            "authorization_endpoint": "https://idp.example.com/auth",
            "token_endpoint": "https://idp.example.com/token",
            "jwks_uri": "https://idp.example.com/.well-known/jwks.json",
        }
        with patch.object(provider, "_discover", new=AsyncMock(return_value=discovery_doc)):
            with patch("everstaff.api.auth.providers.oidc_code.aiohttp.ClientSession", return_value=mock_session_cls):
                with pytest.raises(ValueError, match="No id_token"):
                    await provider.exchange_code("code")

    @pytest.mark.asyncio
    async def test_exchange_code_raises_on_invalid_id_token_signature(self):
        """exchange_code() raises ValueError when id_token signature is invalid."""
        import time as _time

        # Create an id_token signed with a different key than what the JWKS provides
        bad_token = pyjwt.encode(
            {"sub": "u", "exp": int(_time.time()) + 3600},
            "wrong-secret",
            algorithm="HS256",
        )

        provider = OIDCCodeFlowProvider(_make_config())

        # JWKS client that raises DecodeError (simulates signature mismatch)
        mock_jwks_client = MagicMock()
        mock_jwks_client.get_signing_key_from_jwt.side_effect = pyjwt.PyJWTError("invalid signature")
        provider._jwks_client = mock_jwks_client

        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"id_token": bad_token, "access_token": "at"})
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_post_ctx = MagicMock()
        mock_post_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_post_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.post.return_value = mock_post_ctx

        mock_session_cls = MagicMock()
        mock_session_cls.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cls.__aexit__ = AsyncMock(return_value=False)

        discovery_doc = {
            "authorization_endpoint": "https://idp.example.com/auth",
            "token_endpoint": "https://idp.example.com/token",
            "jwks_uri": "https://idp.example.com/.well-known/jwks.json",
        }
        with patch.object(provider, "_discover", new=AsyncMock(return_value=discovery_doc)):
            with patch("everstaff.api.auth.providers.oidc_code.aiohttp.ClientSession", return_value=mock_session_cls):
                with pytest.raises(ValueError, match="id_token"):
                    await provider.exchange_code(bad_token)


class TestBuildAuthorizationUrl:
    @pytest.mark.asyncio
    async def test_returns_url_with_required_params(self):
        provider = OIDCCodeFlowProvider(_make_config())
        discovery_doc = {
            "authorization_endpoint": "https://idp.example.com/auth",
            "token_endpoint": "https://idp.example.com/token",
            "jwks_uri": "https://idp.example.com/.well-known/jwks.json",
        }
        with patch.object(provider, "_discover", new=AsyncMock(return_value=discovery_doc)):
            url = await provider.build_authorization_url("my-state")

        assert url.startswith("https://idp.example.com/auth?")
        assert "response_type=code" in url
        assert "client_id=cid" in url
        assert "state=my-state" in url
        assert "scope=" in url


class TestDiscover:
    @pytest.mark.asyncio
    async def test_discovery_failure_raises_value_error(self):
        """_discover() raises ValueError when the network call fails."""
        provider = OIDCCodeFlowProvider(_make_config())

        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = Exception("connection refused")
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_get_ctx = MagicMock()
        mock_get_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_get_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.get.return_value = mock_get_ctx

        mock_session_cls = MagicMock()
        mock_session_cls.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cls.__aexit__ = AsyncMock(return_value=False)

        with patch("everstaff.api.auth.providers.oidc_code.aiohttp.ClientSession", return_value=mock_session_cls):
            with pytest.raises(ValueError, match="OIDC discovery failed"):
                await provider._discover()

    @pytest.mark.asyncio
    async def test_discovery_cached_across_calls(self):
        """_discover() only makes one network call for the same issuer."""
        provider = OIDCCodeFlowProvider(_make_config())
        discovery_doc = {
            "authorization_endpoint": "https://idp.example.com/auth",
            "token_endpoint": "https://idp.example.com/token",
            "jwks_uri": "https://idp.example.com/.well-known/jwks.json",
        }

        # Pre-populate the instance-level cache
        provider._discovery_cache["https://idp.example.com"] = discovery_doc

        # _discover() should return from cache without making any network call
        result = await provider._discover()
        assert result == discovery_doc

    @pytest.mark.asyncio
    async def test_discovery_populates_cache(self):
        """_discover() stores the result in self._discovery_cache after a successful fetch."""
        provider = OIDCCodeFlowProvider(_make_config())
        discovery_doc = {
            "authorization_endpoint": "https://idp.example.com/auth",
            "token_endpoint": "https://idp.example.com/token",
            "jwks_uri": "https://idp.example.com/.well-known/jwks.json",
        }

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = AsyncMock(return_value=discovery_doc)
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_get_ctx = MagicMock()
        mock_get_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_get_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.get.return_value = mock_get_ctx

        mock_session_cls = MagicMock()
        mock_session_cls.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cls.__aexit__ = AsyncMock(return_value=False)

        with patch("everstaff.api.auth.providers.oidc_code.aiohttp.ClientSession", return_value=mock_session_cls):
            result = await provider._discover()

        assert result == discovery_doc
        # Verify the result is now cached on the instance
        assert provider._discovery_cache.get("https://idp.example.com") == discovery_doc


class TestGenerateState:
    def test_returns_non_empty_string(self):
        state = OIDCCodeFlowProvider.generate_state()
        assert isinstance(state, str)
        assert len(state) > 20

    def test_returns_unique_values(self):
        states = {OIDCCodeFlowProvider.generate_state() for _ in range(10)}
        assert len(states) == 10

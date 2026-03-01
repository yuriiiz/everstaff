"""Tests for auth Pydantic models — config parsing, discriminated union, defaults."""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from everstaff.api.auth.models import (
    AuthConfig,
    JWTProviderConfig,
    OIDCProviderConfig,
    ProxyProviderConfig,
    ProviderConfig,
    UserIdentity,
)


# ---------------------------------------------------------------------------
# UserIdentity
# ---------------------------------------------------------------------------


class TestUserIdentity:
    def test_minimal(self):
        u = UserIdentity(user_id="u-1", provider="jwt")
        assert u.user_id == "u-1"
        assert u.provider == "jwt"
        assert u.name is None
        assert u.email is None

    def test_full(self):
        u = UserIdentity(user_id="u-2", name="Alice", email="alice@example.com", provider="oidc")
        assert u.name == "Alice"
        assert u.email == "alice@example.com"


# ---------------------------------------------------------------------------
# Provider configs — discriminated union
# ---------------------------------------------------------------------------

_adapter = TypeAdapter(ProviderConfig)


class TestProviderConfigDiscriminator:
    def test_oidc(self):
        cfg = _adapter.validate_python({"type": "oidc", "issuer": "https://issuer.example.com"})
        assert isinstance(cfg, OIDCProviderConfig)
        assert cfg.issuer == "https://issuer.example.com"
        assert cfg.audience is None
        assert cfg.claims_mapping == {"user_id": "sub", "name": "name", "email": "email"}

    def test_jwt_defaults(self):
        cfg = _adapter.validate_python({"type": "jwt"})
        assert isinstance(cfg, JWTProviderConfig)
        assert cfg.header == "X-Auth-Token"
        assert cfg.algorithm == "HS256"
        assert cfg.secret is None
        assert cfg.jwks_url is None

    def test_jwt_custom(self):
        cfg = _adapter.validate_python({
            "type": "jwt",
            "header": "Authorization",
            "secret": "${MY_SECRET}",
            "algorithm": "HS512",
        })
        assert cfg.header == "Authorization"
        assert cfg.secret == "${MY_SECRET}"
        assert cfg.algorithm == "HS512"

    def test_proxy(self):
        cfg = _adapter.validate_python({
            "type": "proxy",
            "headers": {"user_id": "X-User-Id", "email": "X-User-Email"},
            "trusted_cidrs": ["10.0.0.0/8"],
        })
        assert isinstance(cfg, ProxyProviderConfig)
        assert cfg.headers == {"user_id": "X-User-Id", "email": "X-User-Email"}
        assert cfg.trusted_cidrs == ["10.0.0.0/8"]

    def test_proxy_requires_headers(self):
        with pytest.raises(ValidationError):
            _adapter.validate_python({"type": "proxy"})

    def test_unknown_type_rejected(self):
        with pytest.raises(ValidationError):
            _adapter.validate_python({"type": "magic", "issuer": "x"})


# ---------------------------------------------------------------------------
# AuthConfig
# ---------------------------------------------------------------------------


class TestAuthConfig:
    def test_defaults(self):
        cfg = AuthConfig()
        assert cfg.enabled is False
        assert "/api/ping" in cfg.public_routes
        assert "/docs" in cfg.public_routes
        assert cfg.providers == []

    def test_enabled_with_providers(self):
        cfg = AuthConfig.model_validate({
            "enabled": True,
            "providers": [
                {"type": "oidc", "issuer": "https://auth.example.com"},
                {"type": "jwt", "secret": "s3cret"},
            ],
        })
        assert cfg.enabled is True
        assert len(cfg.providers) == 2
        assert isinstance(cfg.providers[0], OIDCProviderConfig)
        assert isinstance(cfg.providers[1], JWTProviderConfig)

    def test_custom_public_routes(self):
        cfg = AuthConfig(public_routes=["/health", "/webhooks/*"])
        assert cfg.public_routes == ["/health", "/webhooks/*"]

    def test_allowed_emails_defaults_empty(self):
        cfg = AuthConfig()
        assert cfg.allowed_emails == []

    def test_allowed_emails_roundtrip(self):
        cfg = AuthConfig.model_validate({
            "enabled": True,
            "allowed_emails": ["alice@example.com", "bob@example.com"],
            "providers": [{"type": "jwt", "secret": "s3cret"}],
        })
        assert cfg.allowed_emails == ["alice@example.com", "bob@example.com"]


class TestOIDCCodeFlowProviderConfig:
    def test_defaults(self):
        from everstaff.api.auth.models import OIDCCodeFlowProviderConfig
        cfg = OIDCCodeFlowProviderConfig(
            issuer="https://accounts.google.com",
            client_id="my-client",
            client_secret="my-secret",
            redirect_uri="https://app.example.com/auth/callback",
            cookie_secret="a-32-byte-secret-for-hs256-signing!",
        )
        assert cfg.type == "oidc_code"
        assert cfg.scopes == ["openid", "email", "profile"]
        assert cfg.cookie_name == "agent_session"
        assert cfg.cookie_max_age == 86400

    def test_custom_scopes_and_cookie(self):
        from everstaff.api.auth.models import OIDCCodeFlowProviderConfig
        cfg = OIDCCodeFlowProviderConfig(
            issuer="https://idp.example.com",
            client_id="c",
            client_secret="s",
            redirect_uri="https://app.example.com/auth/callback",
            cookie_secret="secret",
            scopes=["openid"],
            cookie_name="my_session",
            cookie_max_age=3600,
        )
        assert cfg.scopes == ["openid"]
        assert cfg.cookie_name == "my_session"
        assert cfg.cookie_max_age == 3600

    def test_included_in_provider_config_union(self):
        """OIDCCodeFlowProviderConfig must be accepted by the ProviderConfig union."""
        from everstaff.api.auth.models import AuthConfig
        raw = {
            "enabled": True,
            "providers": [
                {
                    "type": "oidc_code",
                    "issuer": "https://accounts.google.com",
                    "client_id": "cid",
                    "client_secret": "csec",
                    "redirect_uri": "https://app.example.com/auth/callback",
                    "cookie_secret": "sec",
                }
            ],
        }
        cfg = AuthConfig.model_validate(raw)
        assert cfg.providers[0].type == "oidc_code"

"""Auth models — Pydantic types for authentication configuration."""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field


class UserIdentity(BaseModel):
    """Authenticated user identity resolved by an auth provider."""

    user_id: str
    name: str | None = None
    email: str | None = None
    provider: str  # "oidc" | "jwt" | "proxy"


class OIDCProviderConfig(BaseModel):
    """Configuration for an OpenID Connect auth provider."""

    type: Literal["oidc"] = "oidc"
    issuer: str
    audience: str | None = None
    claims_mapping: dict[str, str] = {"user_id": "sub", "name": "name", "email": "email"}


class JWTProviderConfig(BaseModel):
    """Configuration for a JWT auth provider."""

    type: Literal["jwt"] = "jwt"
    header: str = "X-Auth-Token"
    secret: str | None = None  # supports ${ENV_VAR}
    algorithm: str = "HS256"
    jwks_url: str | None = None  # for RS256
    claims_mapping: dict[str, str] = {"user_id": "sub", "name": "name", "email": "email"}


class ProxyProviderConfig(BaseModel):
    """Configuration for a trusted-proxy auth provider."""

    type: Literal["proxy"] = "proxy"
    headers: dict[str, str]  # maps identity field -> header name
    trusted_cidrs: list[str] = []  # optional CIDR allowlist


class OIDCCodeFlowProviderConfig(BaseModel):
    """Configuration for OIDC Authorization Code Flow provider."""

    type: Literal["oidc_code"] = "oidc_code"
    issuer: str
    client_id: str
    client_secret: str
    redirect_uri: str
    scopes: list[str] = ["openid", "email", "profile"]
    cookie_secret: str        # HS256 signing key for the session cookie JWT
    cookie_name: str = "agent_session"
    cookie_max_age: int = 86400  # seconds


ProviderConfig = Annotated[
    Union[OIDCProviderConfig, JWTProviderConfig, ProxyProviderConfig, OIDCCodeFlowProviderConfig],
    Field(discriminator="type"),
]


class AuthConfig(BaseModel):
    """Top-level authentication configuration."""

    enabled: bool = False
    public_routes: list[str] = ["/api/ping", "/docs", "/openapi.json", "/redoc"]
    providers: list[ProviderConfig] = []
    allowed_emails: list[str] = []  # empty = allow all authenticated users

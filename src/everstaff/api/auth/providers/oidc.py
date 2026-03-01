"""OpenID Connect (OIDC) authentication provider."""

from __future__ import annotations

import logging

import aiohttp
import jwt as pyjwt
from starlette.requests import Request

from everstaff.api.auth.models import OIDCProviderConfig, UserIdentity
from everstaff.api.auth.providers import AuthProvider

logger = logging.getLogger(__name__)


class OIDCProvider(AuthProvider):
    """Authenticate users via an OIDC ID token (Bearer JWT).

    The provider lazily fetches the OIDC discovery document to obtain the
    ``jwks_uri``, then validates incoming JWTs using the public keys
    published at that endpoint.  Discovery and JWKS results are cached
    after the first successful fetch.
    """

    def __init__(self, config: OIDCProviderConfig) -> None:
        self._config = config
        self._jwks_client: pyjwt.PyJWKClient | None = None
        self._available: bool = True  # set to False if discovery fails

    async def _ensure_jwks_client(self) -> pyjwt.PyJWKClient | None:
        """Lazily initialise the JWKS client from the OIDC discovery endpoint."""
        if self._jwks_client is not None:
            return self._jwks_client
        if not self._available:
            return None
        try:
            discovery_url = (
                f"{self._config.issuer.rstrip('/')}/.well-known/openid-configuration"
            )
            async with aiohttp.ClientSession() as session:
                async with session.get(discovery_url) as resp:
                    resp.raise_for_status()
                    data = await resp.json()

            jwks_uri = data["jwks_uri"]
            self._jwks_client = pyjwt.PyJWKClient(jwks_uri)
            return self._jwks_client
        except Exception as exc:
            logger.warning(
                "OIDC discovery failed for %s: %s", self._config.issuer, exc
            )
            self._available = False
            return None

    async def authenticate(self, request: Request) -> UserIdentity | None:
        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            return None

        token = auth_header[len("Bearer "):]
        if not token:
            return None

        client = await self._ensure_jwks_client()
        if client is None:
            return None

        try:
            signing_key = client.get_signing_key_from_jwt(token)
            if self._config.audience:
                payload = pyjwt.decode(
                    token,
                    signing_key.key,
                    algorithms=["RS256"],
                    audience=self._config.audience,
                )
            else:
                payload = pyjwt.decode(
                    token,
                    signing_key.key,
                    algorithms=["RS256"],
                    options={"verify_aud": False},
                )
        except pyjwt.PyJWTError:
            return None

        mapping = self._config.claims_mapping
        user_id = payload.get(mapping.get("user_id", "sub"))
        if not user_id:
            return None

        name = payload.get(mapping.get("name", "name"))
        email = payload.get(mapping.get("email", "email"))

        return UserIdentity(
            user_id=user_id,
            name=name,
            email=email,
            provider="oidc",
        )

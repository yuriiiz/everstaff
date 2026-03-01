"""JWT authentication provider."""

from __future__ import annotations

import jwt as pyjwt  # alias avoids collision with module name
from starlette.requests import Request

from everstaff.api.auth.models import JWTProviderConfig, UserIdentity
from everstaff.api.auth.providers import AuthProvider
from everstaff.api.auth.utils import expand_env_vars


class JWTProvider(AuthProvider):
    """Authenticate users via a JWT token sent in a request header.

    Supports **HS256** (symmetric, shared secret) and **RS256** (asymmetric,
    JWKS endpoint) verification modes.
    """

    def __init__(self, config: JWTProviderConfig) -> None:
        self._config = config
        self._secret = expand_env_vars(config.secret) if config.secret else None
        self._jwks_client: pyjwt.PyJWKClient | None = None
        if config.jwks_url:
            self._jwks_client = pyjwt.PyJWKClient(config.jwks_url)

    async def authenticate(self, request: Request) -> UserIdentity | None:
        token = request.headers.get(self._config.header)
        if not token:
            return None

        try:
            if self._jwks_client:
                signing_key = self._jwks_client.get_signing_key_from_jwt(token)
                payload = pyjwt.decode(
                    token, signing_key.key, algorithms=[self._config.algorithm]
                )
            else:
                payload = pyjwt.decode(
                    token, self._secret, algorithms=[self._config.algorithm]
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
            provider="jwt",
        )

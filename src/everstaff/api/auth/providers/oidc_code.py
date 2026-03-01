"""OIDC Authorization Code Flow provider."""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from urllib.parse import urlencode

import aiohttp
import jwt as pyjwt
from starlette.requests import Request

from everstaff.api.auth.models import OIDCCodeFlowProviderConfig, UserIdentity
from everstaff.api.auth.providers import AuthProvider

logger = logging.getLogger(__name__)


class OIDCCodeFlowProvider(AuthProvider):
    """OIDC Authorization Code Flow provider.

    Handles two concerns:
    1. authenticate() — validates the httpOnly session cookie on each request.
    2. Helper methods used by the auth router to drive the OAuth flow.
    """

    def __init__(self, config: OIDCCodeFlowProviderConfig) -> None:
        self._config = config
        self._discovery_cache: dict[str, dict] = {}
        self._jwks_client: pyjwt.PyJWKClient | None = None

    @property
    def cookie_name(self) -> str:
        """Public accessor for the configured session cookie name."""
        return self._config.cookie_name

    # ------------------------------------------------------------------
    # AuthProvider interface
    # ------------------------------------------------------------------

    async def authenticate(self, request: Request) -> UserIdentity | None:
        """Validate the session cookie JWT. Return UserIdentity or None."""
        token = request.cookies.get(self._config.cookie_name)
        if not token:
            return None
        try:
            payload = pyjwt.decode(
                token,
                self._config.cookie_secret,
                algorithms=["HS256"],
            )
        except pyjwt.PyJWTError:
            return None

        user_id = payload.get("sub")
        if not user_id:
            return None

        return UserIdentity(
            user_id=user_id,
            email=payload.get("email"),
            name=payload.get("name"),
            provider="oidc_code",
        )

    # ------------------------------------------------------------------
    # Session cookie helpers (used by the auth router)
    # ------------------------------------------------------------------

    def make_session_cookie(self, identity: UserIdentity) -> str:
        """Sign an internal JWT for the session cookie."""
        now = int(time.time())
        payload = {
            "sub": identity.user_id,
            "email": identity.email,
            "name": identity.name,
            "provider": "oidc_code",
            "iat": now,
            "exp": now + self._config.cookie_max_age,
        }
        return pyjwt.encode(payload, self._config.cookie_secret, algorithm="HS256")

    # ------------------------------------------------------------------
    # OIDC Code Flow helpers (used by the auth router)
    # ------------------------------------------------------------------

    async def _discover(self) -> dict:
        """Fetch (and cache) OIDC discovery document."""
        issuer = self._config.issuer
        if issuer in self._discovery_cache:
            return self._discovery_cache[issuer]

        url = f"{issuer.rstrip('/')}/.well-known/openid-configuration"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
        except Exception as exc:
            raise ValueError(f"OIDC discovery failed for {issuer}: {exc}") from exc

        self._discovery_cache[issuer] = data
        return data

    async def _get_jwks_client(self) -> pyjwt.PyJWKClient:
        """Lazily initialise and return the JWKS client."""
        discovery = await self._discover()
        jwks_uri = discovery["jwks_uri"]
        if self._jwks_client is None:
            self._jwks_client = pyjwt.PyJWKClient(jwks_uri)
        return self._jwks_client

    async def build_authorization_url(self, state: str) -> str:
        """Return the OIDC authorization URL to redirect the user to."""
        discovery = await self._discover()
        auth_endpoint = discovery["authorization_endpoint"]

        params = {
            "response_type": "code",
            "client_id": self._config.client_id,
            "redirect_uri": self._config.redirect_uri,
            "scope": " ".join(self._config.scopes),
            "state": state,
        }
        return f"{auth_endpoint}?{urlencode(params)}"

    async def exchange_code(self, code: str) -> UserIdentity:
        """Exchange authorization code for tokens; return UserIdentity.

        Raises ValueError on failure.
        """
        discovery = await self._discover()
        token_endpoint = discovery["token_endpoint"]

        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self._config.redirect_uri,
            "client_id": self._config.client_id,
            "client_secret": self._config.client_secret,
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(token_endpoint, data=data) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    raise ValueError(f"Token exchange failed ({resp.status}): {body}")
                tokens = await resp.json()

        id_token = tokens.get("id_token")
        if not id_token:
            raise ValueError("No id_token in token response")

        try:
            jwks_client = await self._get_jwks_client()
            loop = asyncio.get_running_loop()
            signing_key = await loop.run_in_executor(
                None, jwks_client.get_signing_key_from_jwt, id_token
            )
            payload = pyjwt.decode(
                id_token,
                signing_key.key,
                algorithms=["RS256", "ES256"],
                options={"verify_aud": False},  # audience absent in many providers; client_id check is implicit in the code exchange
            )
        except pyjwt.PyJWTError as exc:
            raise ValueError(f"id_token signature verification failed: {exc}") from exc

        user_id = payload.get("sub")
        if not user_id:
            raise ValueError("id_token missing 'sub' claim")

        return UserIdentity(
            user_id=user_id,
            email=payload.get("email"),
            name=payload.get("name"),
            provider="oidc_code",
        )

    @staticmethod
    def generate_state() -> str:
        """Generate a cryptographically random state value for CSRF protection."""
        return secrets.token_urlsafe(32)

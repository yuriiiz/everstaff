"""Auth middleware — intercepts requests and resolves user identity."""

from __future__ import annotations

import logging

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import RedirectResponse

from everstaff.api.auth.models import AuthConfig, UserIdentity
from everstaff.api.auth.providers import AuthProvider
from everstaff.api.auth.utils import matches_route

logger = logging.getLogger(__name__)


class AuthMiddleware(BaseHTTPMiddleware):
    """Authenticate every request using the configured provider chain.

    * Public routes (matched via ``matches_route``) skip authentication.
    * Providers are tried in order; the first to return a ``UserIdentity`` wins.
    * ``HTTPException`` (e.g. 403 from ``ProxyProvider``) is converted to a
      JSON response (re-raising from ``BaseHTTPMiddleware.dispatch`` would be
      swallowed by Starlette's ``ServerErrorMiddleware``).
    * Any other exception is logged as a warning and the next provider is tried.
    * If no provider succeeds, a **401** JSON response is returned.
    """

    def __init__(self, app, *, auth_config: AuthConfig) -> None:  # type: ignore[override]
        super().__init__(app)
        self._public_routes = auth_config.public_routes
        self._providers = self._build_providers(auth_config.providers)
        self._allowed_emails: set[str] = {
            e.lower() for e in auth_config.allowed_emails
        }
        # Detect whether an OIDC Code Flow provider is configured so
        # browser navigations can be redirected to /auth/login instead
        # of receiving a raw 401 JSON response.
        from everstaff.api.auth.models import OIDCCodeFlowProviderConfig

        self._has_oidc_code_flow = any(
            isinstance(p, OIDCCodeFlowProviderConfig)
            for p in auth_config.providers
        )

    @staticmethod
    def _build_providers(provider_configs: list) -> list[AuthProvider]:
        """Instantiate concrete providers from config objects."""
        providers: list[AuthProvider] = []
        for cfg in provider_configs:
            if cfg.type == "oidc":
                from everstaff.api.auth.providers.oidc import OIDCProvider

                providers.append(OIDCProvider(cfg))
            elif cfg.type == "jwt":
                from everstaff.api.auth.providers.jwt import JWTProvider

                providers.append(JWTProvider(cfg))
            elif cfg.type == "proxy":
                from everstaff.api.auth.providers.proxy import ProxyProvider

                providers.append(ProxyProvider(cfg))
            elif cfg.type == "oidc_code":
                from everstaff.api.auth.providers.oidc_code import OIDCCodeFlowProvider

                providers.append(OIDCCodeFlowProvider(cfg))
        return providers

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        is_public = matches_route(request.url.path, self._public_routes)

        # For public routes: attempt optional auth (populate user if possible),
        # but never reject — fall through unconditionally.
        if is_public:
            for provider in self._providers:
                try:
                    identity = await provider.authenticate(request)
                    if identity is not None:
                        request.state.user = identity
                        break
                except Exception:  # noqa: BLE001
                    continue
            return await call_next(request)

        # Try each provider in order
        for provider in self._providers:
            try:
                identity = await provider.authenticate(request)
                if identity is not None:
                    # Email whitelist check
                    if self._allowed_emails:
                        email = (identity.email or "").lower()
                        if email not in self._allowed_emails:
                            return JSONResponse(
                                status_code=403,
                                content={
                                    "error": "forbidden",
                                    "detail": "Email not in allowed list",
                                },
                            )
                    request.state.user = identity
                    response = await call_next(request)
                    return response
            except HTTPException as http_exc:
                # Convert to JSONResponse — re-raising from
                # BaseHTTPMiddleware.dispatch would be caught by
                # ServerErrorMiddleware and turned into a 500.
                return JSONResponse(
                    status_code=http_exc.status_code,
                    content={
                        "error": http_exc.detail
                        if isinstance(http_exc.detail, str)
                        else str(http_exc.detail),
                    },
                )
            except Exception as exc:
                logger.warning(
                    "Auth provider %s failed: %s", type(provider).__name__, exc
                )
                continue

        # All providers returned None.
        # If OIDC Code Flow is configured and the request is a browser
        # navigation (Accept: text/html), redirect to the login page so
        # the user enters the OAuth flow instead of seeing a raw 401.
        if self._has_oidc_code_flow:
            accept = request.headers.get("accept", "")
            if "text/html" in accept:
                return RedirectResponse("/auth/login")

        return JSONResponse(
            status_code=401,
            content={
                "error": "unauthorized",
                "detail": "No valid credentials provided",
            },
        )


async def get_current_user(request: Request) -> UserIdentity:
    """FastAPI dependency to extract authenticated user from request."""
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


async def authenticate_token(
    providers: list[AuthProvider], token: str
) -> UserIdentity | None:
    """Authenticate a bare token (e.g. from a WebSocket query param).

    Builds a minimal fake :class:`~starlette.requests.Request` with the token
    placed in:

    * ``Authorization: Bearer {token}`` — for OIDC providers
    * The configured JWT header — for JWT providers

    Each provider is tried in order; the first to return a
    :class:`UserIdentity` wins.  Exceptions are caught and logged so a
    failing provider never blocks the rest of the chain.
    """
    from starlette.requests import Request as _Request

    from everstaff.api.auth.providers.jwt import JWTProvider

    headers: list[tuple[bytes, bytes]] = [
        (b"authorization", f"Bearer {token}".encode()),
    ]
    # Also inject the token into every custom JWT header so the JWT
    # provider can find it regardless of its ``header`` setting.
    for provider in providers:
        if isinstance(provider, JWTProvider):
            hdr = provider._config.header.lower().encode()
            if hdr != b"authorization":
                headers.append((hdr, token.encode()))

    scope: dict = {
        "type": "http",
        "method": "GET",
        "path": "/ws",
        "query_string": b"",
        "headers": headers,
    }
    fake_request = _Request(scope)

    for provider in providers:
        try:
            identity = await provider.authenticate(fake_request)
            if identity is not None:
                return identity
        except Exception:  # noqa: BLE001
            continue
    return None

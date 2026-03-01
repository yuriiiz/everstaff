"""Trusted reverse-proxy authentication provider."""

from __future__ import annotations

import ipaddress

from fastapi import HTTPException
from starlette.requests import Request

from everstaff.api.auth.models import ProxyProviderConfig, UserIdentity
from everstaff.api.auth.providers import AuthProvider


class ProxyProvider(AuthProvider):
    """Authenticate users via headers set by a trusted reverse proxy.

    The proxy (e.g. nginx, Caddy, Traefik) terminates auth and forwards
    the resolved identity as request headers.  An optional ``trusted_cidrs``
    allowlist restricts which source IPs are accepted.
    """

    def __init__(self, config: ProxyProviderConfig) -> None:
        self._config = config
        # Pre-parse CIDRs at init time so invalid values fail fast.
        self._networks = [
            ipaddress.ip_network(c, strict=False) for c in config.trusted_cidrs
        ]

    async def authenticate(self, request: Request) -> UserIdentity | None:
        # 1. Check if user_id header exists and is non-empty.
        user_id_header = self._config.headers.get("user_id")
        if not user_id_header:
            return None

        user_id = request.headers.get(user_id_header)
        if not user_id:
            return None

        # 2. If trusted_cidrs is configured, validate the client IP.
        if self._networks:
            client_ip = ipaddress.ip_address(request.client.host)
            if not any(client_ip in network for network in self._networks):
                raise HTTPException(
                    status_code=403, detail="Request source not trusted"
                )

        # 3. Extract optional identity fields from headers.
        name_header = self._config.headers.get("name")
        email_header = self._config.headers.get("email")

        name = request.headers.get(name_header) if name_header else None
        email = request.headers.get(email_header) if email_header else None

        # 4. Return the resolved identity.
        return UserIdentity(
            user_id=user_id,
            name=name,
            email=email,
            provider="proxy",
        )

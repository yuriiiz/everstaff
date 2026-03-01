"""Tests for the trusted reverse-proxy authentication provider."""

from __future__ import annotations

import ipaddress

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from everstaff.api.auth.models import ProxyProviderConfig
from everstaff.api.auth.providers.proxy import ProxyProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEFAULT_HEADERS_MAP = {
    "user_id": "X-Forwarded-User",
    "name": "X-Forwarded-Name",
    "email": "X-Forwarded-Email",
}


def _make_request(
    headers: dict[str, str] | None = None,
    client_host: str = "127.0.0.1",
) -> Request:
    """Build a minimal Starlette ``Request`` with the given headers and client IP."""
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "query_string": b"",
        "headers": [
            (k.lower().encode(), v.encode()) for k, v in (headers or {}).items()
        ],
        "client": (client_host, 0),
    }
    return Request(scope)


# ---------------------------------------------------------------------------
# Auth success
# ---------------------------------------------------------------------------


class TestAuthSuccess:
    @pytest.mark.asyncio
    async def test_all_headers_present(self):
        provider = ProxyProvider(
            ProxyProviderConfig(headers=_DEFAULT_HEADERS_MAP)
        )
        request = _make_request(
            headers={
                "X-Forwarded-User": "alice",
                "X-Forwarded-Name": "Alice Smith",
                "X-Forwarded-Email": "alice@example.com",
            }
        )
        identity = await provider.authenticate(request)

        assert identity is not None
        assert identity.user_id == "alice"
        assert identity.name == "Alice Smith"
        assert identity.email == "alice@example.com"
        assert identity.provider == "proxy"

    @pytest.mark.asyncio
    async def test_optional_headers_missing(self):
        """name and email headers may be absent — should still succeed."""
        provider = ProxyProvider(
            ProxyProviderConfig(headers={"user_id": "X-Forwarded-User"})
        )
        request = _make_request(headers={"X-Forwarded-User": "bob"})
        identity = await provider.authenticate(request)

        assert identity is not None
        assert identity.user_id == "bob"
        assert identity.name is None
        assert identity.email is None
        assert identity.provider == "proxy"


# ---------------------------------------------------------------------------
# Returns None when provider doesn't apply
# ---------------------------------------------------------------------------


class TestReturnsNone:
    @pytest.mark.asyncio
    async def test_user_id_header_missing(self):
        provider = ProxyProvider(
            ProxyProviderConfig(headers=_DEFAULT_HEADERS_MAP)
        )
        request = _make_request(headers={"X-Forwarded-Name": "Alice"})
        assert await provider.authenticate(request) is None

    @pytest.mark.asyncio
    async def test_user_id_header_empty(self):
        provider = ProxyProvider(
            ProxyProviderConfig(headers=_DEFAULT_HEADERS_MAP)
        )
        request = _make_request(headers={"X-Forwarded-User": ""})
        assert await provider.authenticate(request) is None


# ---------------------------------------------------------------------------
# CIDR trust validation
# ---------------------------------------------------------------------------


class TestTrustedCIDRs:
    @pytest.mark.asyncio
    async def test_allowed_ip_passes(self):
        provider = ProxyProvider(
            ProxyProviderConfig(
                headers=_DEFAULT_HEADERS_MAP,
                trusted_cidrs=["10.0.0.0/8"],
            )
        )
        request = _make_request(
            headers={"X-Forwarded-User": "alice"},
            client_host="10.1.2.3",
        )
        identity = await provider.authenticate(request)
        assert identity is not None
        assert identity.user_id == "alice"

    @pytest.mark.asyncio
    async def test_disallowed_ip_raises_403(self):
        provider = ProxyProvider(
            ProxyProviderConfig(
                headers=_DEFAULT_HEADERS_MAP,
                trusted_cidrs=["10.0.0.0/8"],
            )
        )
        request = _make_request(
            headers={"X-Forwarded-User": "alice"},
            client_host="192.168.1.1",
        )
        with pytest.raises(HTTPException) as exc_info:
            await provider.authenticate(request)

        assert exc_info.value.status_code == 403
        assert "not trusted" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_empty_trusted_cidrs_allows_any_ip(self):
        """When trusted_cidrs is empty, all source IPs are accepted."""
        provider = ProxyProvider(
            ProxyProviderConfig(
                headers=_DEFAULT_HEADERS_MAP,
                trusted_cidrs=[],
            )
        )
        request = _make_request(
            headers={"X-Forwarded-User": "alice"},
            client_host="203.0.113.99",
        )
        identity = await provider.authenticate(request)
        assert identity is not None
        assert identity.user_id == "alice"

    @pytest.mark.asyncio
    async def test_multiple_cidrs(self):
        """IP matching any one CIDR in the list should pass."""
        provider = ProxyProvider(
            ProxyProviderConfig(
                headers=_DEFAULT_HEADERS_MAP,
                trusted_cidrs=["10.0.0.0/8", "172.16.0.0/12"],
            )
        )
        request = _make_request(
            headers={"X-Forwarded-User": "alice"},
            client_host="172.20.0.1",
        )
        identity = await provider.authenticate(request)
        assert identity is not None


# ---------------------------------------------------------------------------
# CIDR parsing at init time
# ---------------------------------------------------------------------------


class TestCIDRParsing:
    def test_cidrs_parsed_at_init(self):
        provider = ProxyProvider(
            ProxyProviderConfig(
                headers=_DEFAULT_HEADERS_MAP,
                trusted_cidrs=["10.0.0.0/8", "192.168.0.0/16"],
            )
        )
        assert len(provider._networks) == 2
        assert all(
            isinstance(n, ipaddress.IPv4Network) for n in provider._networks
        )

    def test_invalid_cidr_raises_at_init(self):
        with pytest.raises(ValueError):
            ProxyProvider(
                ProxyProviderConfig(
                    headers=_DEFAULT_HEADERS_MAP,
                    trusted_cidrs=["not-a-cidr"],
                )
            )

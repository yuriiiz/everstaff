"""Tests for Feishu OAuth Device Flow (RFC 8628)."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from everstaff.feishu.device_flow import (
    resolve_oauth_endpoints,
    request_device_authorization,
    poll_device_token,
)


def test_resolve_endpoints_feishu():
    ep = resolve_oauth_endpoints("feishu")
    assert ep["device_authorization"] == "https://accounts.feishu.cn/oauth/v1/device_authorization"
    assert ep["token"] == "https://open.feishu.cn/open-apis/authen/v2/oauth/token"


def test_resolve_endpoints_lark():
    ep = resolve_oauth_endpoints("lark")
    assert "larksuite.com" in ep["device_authorization"]
    assert "larksuite.com" in ep["token"]


@pytest.mark.asyncio
async def test_request_device_authorization_success():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "device_code": "dev123",
        "user_code": "ABCD-1234",
        "verification_uri": "https://accounts.feishu.cn/oauth/device",
        "verification_uri_complete": "https://accounts.feishu.cn/oauth/device?user_code=ABCD-1234",
        "expires_in": 240,
        "interval": 5,
    }

    with patch("httpx.AsyncClient.post", return_value=mock_response):
        result = await request_device_authorization("app_id", "app_secret", scope="calendar:calendar", domain="feishu")
        assert result["device_code"] == "dev123"
        assert result["verification_uri_complete"].startswith("https://")
        assert result["expires_in"] == 240
        assert result["interval"] == 5


@pytest.mark.asyncio
async def test_request_device_authorization_failure():
    mock_response = MagicMock()
    mock_response.status_code = 400
    mock_response.json.return_value = {"error": "invalid_client", "error_description": "bad creds"}

    with patch("httpx.AsyncClient.post", return_value=mock_response):
        with pytest.raises(RuntimeError, match="bad creds"):
            await request_device_authorization("bad", "bad", domain="feishu")


@pytest.mark.asyncio
async def test_poll_device_token_success():
    """Simulate: pending -> pending -> success."""
    responses = [
        {"error": "authorization_pending"},
        {"error": "authorization_pending"},
        {"access_token": "at_xxx", "refresh_token": "rt_xxx", "expires_in": 7200, "refresh_token_expires_in": 604800, "scope": "calendar:calendar"},
    ]
    call_count = 0

    async def mock_post(url, **kwargs):
        nonlocal call_count
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = responses[min(call_count, len(responses) - 1)]
        call_count += 1
        return resp

    with patch("httpx.AsyncClient.post", side_effect=mock_post):
        result = await poll_device_token(
            app_id="app", app_secret="secret", device_code="dev123",
            interval=0.01, expires_in=10, domain="feishu",
        )
        assert result["ok"] is True
        assert result["token"]["access_token"] == "at_xxx"
        assert result["token"]["scope"] == "calendar:calendar"


@pytest.mark.asyncio
async def test_poll_device_token_denied():
    async def mock_post(url, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"error": "access_denied"}
        return resp

    with patch("httpx.AsyncClient.post", side_effect=mock_post):
        result = await poll_device_token(
            app_id="app", app_secret="secret", device_code="dev123",
            interval=0.01, expires_in=10, domain="feishu",
        )
        assert result["ok"] is False
        assert result["error"] == "access_denied"

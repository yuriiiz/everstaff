"""End-to-end smoke test for Feishu tool flow."""
import pytest
import time
from unittest.mock import AsyncMock, patch

from everstaff.tools.feishu.auto_auth import handle_auth_error
from everstaff.tools.feishu.errors import UserAuthRequiredError
from everstaff.tools.feishu.token_store import FileTokenStore, StoredToken
from everstaff.tools.feishu.uat_client import call_with_uat


@pytest.mark.asyncio
async def test_full_flow_already_authorized(tmp_path):
    """When user already has a valid token, tool call should work directly."""
    store = FileTokenStore(base_dir=tmp_path)
    now = int(time.time() * 1000)
    await store.set(StoredToken(
        app_id="app", user_open_id="ou_user1",
        access_token="valid_at", refresh_token="valid_rt",
        expires_at=now + 600_000, refresh_expires_at=now + 86400_000,
        scope="calendar:calendar", granted_at=now,
    ))

    call_log = []

    async def fake_api_call(uat: str) -> str:
        call_log.append(uat)
        return '{"code": 0, "data": {"event_id": "ev_123"}}'

    result = await call_with_uat(
        user_open_id="ou_user1", app_id="app", app_secret="secret",
        domain="feishu", fn=fake_api_call, token_store=store,
    )
    assert "ev_123" in result
    assert call_log == ["valid_at"]


@pytest.mark.asyncio
async def test_full_flow_needs_auth(tmp_path):
    """When no token exists, auto_auth should send card and start polling."""
    store = FileTokenStore(base_dir=tmp_path)
    err = UserAuthRequiredError(
        user_open_id="ou_user1",
        required_scopes=["calendar:calendar"],
        app_id="app",
    )

    mock_send = AsyncMock(return_value="msg_001")

    with patch("everstaff.tools.feishu.auto_auth.request_device_authorization") as mock_dev:
        mock_dev.return_value = {
            "device_code": "dev_abc",
            "verification_uri_complete": "https://feishu.cn/auth?code=XYZ",
            "expires_in": 240,
            "interval": 5,
        }
        result = await handle_auth_error(
            err=err, app_id="app", app_secret="secret",
            domain="feishu", send_card_fn=mock_send,
            token_store=store, poll=False,
        )

    assert result["awaiting_authorization"] is True
    mock_send.assert_called_once()

"""Tests for UAT lifecycle management (refresh + retry)."""
import pytest
import time
from unittest.mock import AsyncMock, patch, MagicMock

from everstaff.tools.feishu.token_store import StoredToken, FileTokenStore
from everstaff.tools.feishu.uat_client import call_with_uat, refresh_uat, NeedAuthorizationError


@pytest.mark.asyncio
async def test_call_with_uat_valid_token(tmp_path):
    store = FileTokenStore(base_dir=tmp_path)
    now = int(time.time() * 1000)
    await store.set(StoredToken(
        app_id="app", user_open_id="user",
        access_token="valid_token", refresh_token="rt",
        expires_at=now + 600_000, refresh_expires_at=now + 86400_000,
        scope="cal", granted_at=now,
    ))

    fn = AsyncMock(return_value="result")
    result = await call_with_uat(
        user_open_id="user", app_id="app", app_secret="secret",
        domain="feishu", fn=fn, token_store=store,
    )
    assert result == "result"
    fn.assert_called_once_with("valid_token")


@pytest.mark.asyncio
async def test_call_with_uat_no_token(tmp_path):
    store = FileTokenStore(base_dir=tmp_path)
    fn = AsyncMock()
    with pytest.raises(NeedAuthorizationError):
        await call_with_uat(
            user_open_id="user", app_id="app", app_secret="secret",
            domain="feishu", fn=fn, token_store=store,
        )


@pytest.mark.asyncio
async def test_call_with_uat_refreshes_expired(tmp_path):
    store = FileTokenStore(base_dir=tmp_path)
    now = int(time.time() * 1000)
    await store.set(StoredToken(
        app_id="app", user_open_id="user",
        access_token="old_token", refresh_token="rt_valid",
        expires_at=now - 1000,  # expired
        refresh_expires_at=now + 86400_000,  # refresh still valid
        scope="cal", granted_at=now,
    ))

    fn = AsyncMock(return_value="ok")

    with patch("everstaff.tools.feishu.uat_client.refresh_uat") as mock_refresh:
        mock_refresh.return_value = {
            "access_token": "new_token", "refresh_token": "new_rt",
            "expires_in": 7200, "refresh_token_expires_in": 604800,
        }
        result = await call_with_uat(
            user_open_id="user", app_id="app", app_secret="secret",
            domain="feishu", fn=fn, token_store=store,
        )
    assert result == "ok"
    fn.assert_called_once_with("new_token")

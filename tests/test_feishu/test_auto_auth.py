"""Tests for auto-auth middleware."""
import json

import pytest
from unittest.mock import AsyncMock, patch

from everstaff.feishu.auto_auth import handle_auth_error, UserAuthRequiredError


@pytest.mark.asyncio
async def test_handle_auth_error_sends_card():
    """When UserAuthRequiredError is raised, auto_auth should initiate Device Flow."""
    err = UserAuthRequiredError(
        user_open_id="ou_user1",
        required_scopes=["calendar:calendar"],
        app_id="app123",
    )

    mock_send_card = AsyncMock(return_value="msg_id_123")

    with patch("everstaff.feishu.auto_auth.request_device_authorization") as mock_device:
        mock_device.return_value = {
            "device_code": "dev123",
            "verification_uri_complete": "https://feishu.cn/auth?code=ABC",
            "expires_in": 240,
            "interval": 5,
        }

        result = await handle_auth_error(
            err=err,
            app_id="app123",
            app_secret="secret",
            domain="feishu",
            send_card_fn=mock_send_card,
            poll=False,  # don't actually poll in test
        )

    assert result["awaiting_authorization"] is True
    mock_send_card.assert_called_once()
    card_arg = mock_send_card.call_args[0][0]
    assert "前往授权" in json.dumps(card_arg, ensure_ascii=False)

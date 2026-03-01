# tests/api/test_lark_webhook.py
import pytest
from httpx import AsyncClient, ASGITransport
from everstaff.api import create_app


@pytest.mark.asyncio
async def test_lark_url_verification(tmp_path):
    """Lark webhook must handle URL verification challenge."""
    app = create_app(sessions_dir=str(tmp_path))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/webhooks/lark", json={
            "type": "url_verification",
            "challenge": "test_challenge_123",
        })
    assert resp.status_code == 200
    assert resp.json()["challenge"] == "test_challenge_123"


@pytest.mark.asyncio
async def test_lark_webhook_no_hitl_id_is_ignored(tmp_path):
    """Lark webhook with no hitl_id must return 'ignored'."""
    app = create_app(sessions_dir=str(tmp_path))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/webhooks/lark", json={"action": {"value": {}}})
    assert resp.status_code == 200
    assert resp.json()["msg"] == "ignored"


@pytest.mark.asyncio
async def test_lark_channel_config_loaded(tmp_path):
    """ChannelManager should support Lark channel from config."""
    from everstaff.core.config import FrameworkConfig, ChannelConfig
    config = FrameworkConfig(
        sessions_dir=str(tmp_path),
        channels=[
            ChannelConfig(
                type="lark",
                app_id="app_test",
                app_secret="secret_test",
                verification_token="vtoken",
                chat_id="chat_test",
            )
        ],
    )
    app = create_app(config=config, sessions_dir=str(tmp_path))
    # Should have 2 channels: LarkChannel + WebSocketChannel
    assert len(app.state.channel_manager._channels) == 2


@pytest.mark.asyncio
async def test_lark_ws_channel_config_loaded(tmp_path):
    """create_app with lark_ws config must register LarkWsChannel in ChannelManager."""
    from everstaff.core.config import FrameworkConfig, ChannelConfig
    from everstaff.channels.lark_ws import LarkWsChannel
    config = FrameworkConfig(
        sessions_dir=str(tmp_path),
        channels=[
            ChannelConfig(
                type="lark_ws",
                app_id="app_test",
                app_secret="secret_test",
                chat_id="chat_test",
            )
        ],
    )
    app = create_app(config=config, sessions_dir=str(tmp_path))
    # Expect 2 channels: LarkWsChannel + WebSocketChannel
    assert len(app.state.channel_manager._channels) == 2
    assert isinstance(app.state.channel_manager._channels[0], LarkWsChannel)


@pytest.mark.asyncio
async def test_lark_ws_channel_manager_injected(tmp_path):
    """create_app must inject channel_manager into LarkWsChannel after construction."""
    from everstaff.core.config import FrameworkConfig, ChannelConfig
    from everstaff.channels.lark_ws import LarkWsChannel
    config = FrameworkConfig(
        sessions_dir=str(tmp_path),
        channels=[
            ChannelConfig(
                type="lark_ws",
                app_id="app_test",
                app_secret="secret_test",
                chat_id="chat_test",
            )
        ],
    )
    app = create_app(config=config, sessions_dir=str(tmp_path))
    ws_ch = app.state.channel_manager._channels[0]
    assert isinstance(ws_ch, LarkWsChannel)
    assert ws_ch._channel_manager is app.state.channel_manager

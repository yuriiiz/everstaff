"""Tests for typed channel configs and named channel registry (Task 2)."""
import pytest


def test_lark_channel_config_fields():
    from everstaff.core.config import LarkChannelConfig
    cfg = LarkChannelConfig(type="lark", app_id="cli_x", app_secret="s", chat_id="oc_x")
    assert cfg.app_id == "cli_x"
    assert cfg.chat_id == "oc_x"
    assert cfg.domain == "feishu"


def test_lark_ws_channel_config_fields():
    from everstaff.core.config import LarkWsChannelConfig
    cfg = LarkWsChannelConfig(type="lark_ws", app_id="cli_x", app_secret="s")
    assert cfg.type == "lark_ws"


def test_webhook_channel_config_fields():
    from everstaff.core.config import WebhookChannelConfig
    cfg = WebhookChannelConfig(type="webhook", url="https://example.com/hook")
    assert cfg.url == "https://example.com/hook"
    assert cfg.headers == {}


def test_framework_config_channels_is_dict():
    from everstaff.core.config import FrameworkConfig
    cfg = FrameworkConfig()
    assert isinstance(cfg.channels, dict)
    assert cfg.channels == {}


def test_framework_config_channels_parsed_from_dict():
    from everstaff.core.config import FrameworkConfig, LarkChannelConfig, WebhookChannelConfig
    cfg = FrameworkConfig(channels={
        "lark-main": {"type": "lark", "app_id": "cli_x", "app_secret": "s", "chat_id": "oc_x"},
        "my-hook": {"type": "webhook", "url": "https://example.com/hook"},
    })
    assert "lark-main" in cfg.channels
    assert "my-hook" in cfg.channels
    assert isinstance(cfg.channels["lark-main"], LarkChannelConfig)
    assert isinstance(cfg.channels["my-hook"], WebhookChannelConfig)


def test_channel_config_discriminator_unknown_type_raises():
    from everstaff.core.config import FrameworkConfig
    with pytest.raises(Exception):
        FrameworkConfig(channels={"bad": {"type": "telegram"}})


def test_build_channel_registry_returns_named_dict(tmp_path):
    from everstaff.core.config import FrameworkConfig, LarkChannelConfig
    from everstaff.core.factories import build_channel_registry
    from everstaff.channels.lark import LarkChannel
    from everstaff.storage.local import LocalFileStore

    store = LocalFileStore(str(tmp_path))
    cfg = FrameworkConfig(channels={
        "my-lark": {"type": "lark", "app_id": "cli_x", "app_secret": "s", "chat_id": "oc_x"},
    })
    registry = build_channel_registry(cfg, store)
    assert "my-lark" in registry
    assert isinstance(registry["my-lark"], LarkChannel)

"""Integration tests for Feishu tools config."""
from everstaff.core.config import LarkWsChannelConfig


def test_lark_ws_config_with_feishu_tools():
    cfg = LarkWsChannelConfig(
        type="lark_ws",
        app_id="cli_xxx",
        app_secret="secret",
        chat_id="oc_xxx",
        domain="feishu",
        feishu_tools=["docs", "calendar"],
    )
    assert cfg.feishu_tools == ["docs", "calendar"]


def test_lark_ws_config_default_no_tools():
    cfg = LarkWsChannelConfig(
        type="lark_ws",
        app_id="cli_xxx",
        app_secret="secret",
        chat_id="oc_xxx",
    )
    assert cfg.feishu_tools == []

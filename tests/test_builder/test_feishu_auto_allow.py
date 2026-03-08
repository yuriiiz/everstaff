"""Tests for auto_allow_tools config on LarkWsChannelConfig."""
from everstaff.core.config import LarkWsChannelConfig


def test_auto_allow_tools_defaults_empty():
    cfg = LarkWsChannelConfig(type="lark_ws")
    assert cfg.auto_allow_tools == []


def test_auto_allow_tools_accepts_list():
    cfg = LarkWsChannelConfig(type="lark_ws", auto_allow_tools=["feishu_send_message"])
    assert cfg.auto_allow_tools == ["feishu_send_message"]


def test_auto_allow_tools_wildcard():
    cfg = LarkWsChannelConfig(type="lark_ws", auto_allow_tools=["*"])
    assert cfg.auto_allow_tools == ["*"]

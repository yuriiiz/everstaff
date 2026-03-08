"""Tests for LarkWs connection registry construction."""
import pytest
from everstaff.core.config import LarkWsChannelConfig


def test_build_lark_connections_deduplicates():
    """Two configs with same app_id should produce one connection."""
    from everstaff.core.factories import build_lark_connections

    configs = {
        "ch_a": LarkWsChannelConfig(type="lark_ws", app_id="cli_xxx", app_secret="s", chat_id="oc_a"),
        "ch_b": LarkWsChannelConfig(type="lark_ws", app_id="cli_xxx", app_secret="s", chat_id="oc_b"),
    }
    connections = build_lark_connections(configs)
    assert len(connections) == 1
    assert "cli_xxx" in connections


def test_build_lark_connections_multiple_apps():
    """Different app_ids get separate connections."""
    from everstaff.core.factories import build_lark_connections

    configs = {
        "ch_a": LarkWsChannelConfig(type="lark_ws", app_id="app1", app_secret="s1", chat_id="oc_a"),
        "ch_b": LarkWsChannelConfig(type="lark_ws", app_id="app2", app_secret="s2", chat_id="oc_b"),
    }
    connections = build_lark_connections(configs)
    assert len(connections) == 2
    assert "app1" in connections
    assert "app2" in connections


def test_build_lark_connections_ignores_non_lark():
    """Non-LarkWs configs should be ignored."""
    from everstaff.core.factories import build_lark_connections
    from everstaff.core.config import WebhookChannelConfig

    configs = {
        "lark": LarkWsChannelConfig(type="lark_ws", app_id="app1", app_secret="s", chat_id="oc_a"),
        "webhook": WebhookChannelConfig(type="webhook", url="http://example.com"),
    }
    connections = build_lark_connections(configs)
    assert len(connections) == 1
    assert "app1" in connections


def test_build_channel_uses_shared_connection():
    """build_channel with lark_connections should reuse the shared connection."""
    import sys
    from types import ModuleType
    from unittest.mock import MagicMock

    # Ensure lark_oapi import check passes in test environment
    if "lark_oapi" not in sys.modules:
        sys.modules["lark_oapi"] = ModuleType("lark_oapi")

    from everstaff.core.factories import build_channel, build_lark_connections

    configs = {
        "ch_a": LarkWsChannelConfig(type="lark_ws", app_id="app1", app_secret="s", chat_id="oc_a"),
        "ch_b": LarkWsChannelConfig(type="lark_ws", app_id="app1", app_secret="s", chat_id="oc_b"),
    }
    connections = build_lark_connections(configs)

    file_store = MagicMock()

    ch_a = build_channel(configs["ch_a"], file_store, lark_connections=connections)
    ch_b = build_channel(configs["ch_b"], file_store, lark_connections=connections)

    assert ch_a._connection is ch_b._connection
    assert ch_a._chat_id == "oc_a"
    assert ch_b._chat_id == "oc_b"

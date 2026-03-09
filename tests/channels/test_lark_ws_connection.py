"""Tests for LarkWsConnection."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from everstaff.channels.lark_ws_connection import LarkWsConnection


def test_connection_init():
    conn = LarkWsConnection(
        app_id="cli_xxx", app_secret="secret", domain="feishu",
    )
    assert conn._app_id == "cli_xxx"
    assert conn._started is False


def test_register_chat_route():
    conn = LarkWsConnection(
        app_id="cli_xxx", app_secret="secret", domain="feishu",
    )
    conn.register_chat_route("oc_chatA", "agent_a")
    conn.register_chat_route("oc_chatB", "agent_b")
    assert conn._chat_to_agent == {"oc_chatA": "agent_a", "oc_chatB": "agent_b"}


def test_resolve_agent_for_chat():
    conn = LarkWsConnection(
        app_id="cli_xxx", app_secret="secret", domain="feishu",
    )
    conn.register_chat_route("oc_chatA", "agent_a")
    assert conn._resolve_agent("oc_chatA") == "agent_a"
    assert conn._resolve_agent("oc_unknown") is None


def test_parse_card_action_hitl():
    value = {"type": "hitl", "hitl_id": "h1", "decision": "approved", "grant_scope": "session"}
    action_type, parsed = LarkWsConnection._parse_card_value(value)
    assert action_type == "hitl"
    assert parsed["hitl_id"] == "h1"


def test_parse_card_action_unknown_type():
    value = {"type": "feedback", "rating": 5}
    action_type, parsed = LarkWsConnection._parse_card_value(value)
    assert action_type == "feedback"
    assert parsed["rating"] == 5


def test_register_card_handler():
    conn = LarkWsConnection(app_id="cli_xxx", app_secret="secret")
    handler = lambda data: {"toast": {"type": "success"}}
    conn.register_card_handler(handler)
    assert conn._external_card_handler is handler


def test_register_message_handler():
    conn = LarkWsConnection(app_id="cli_xxx", app_secret="secret")
    handler = lambda data: None
    conn.register_message_handler(handler)
    assert conn._external_message_handler is handler

"""Tests for Feishu auth card builders."""
import json

from everstaff.feishu.auth_cards import build_auth_card, build_auth_success_card


def test_build_auth_card():
    card = build_auth_card(
        verification_uri="https://accounts.feishu.cn/oauth/device?code=ABC",
        expires_min=4,
        scopes=["calendar:calendar", "task:task:write"],
        bot_name="MyBot",
    )
    content = json.dumps(card, ensure_ascii=False)
    assert "calendar:calendar" in content
    assert "task:task:write" in content
    assert "前往授权" in content
    assert card["header"]["template"] == "blue"


def test_build_auth_success_card():
    card = build_auth_success_card(bot_name="MyBot")
    content = json.dumps(card, ensure_ascii=False)
    assert "授权成功" in content
    assert card["header"]["template"] == "green"

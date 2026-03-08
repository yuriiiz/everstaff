"""Feishu interactive card builders for OAuth authorization flow."""
from __future__ import annotations


def build_auth_card(
    *,
    verification_uri: str,
    expires_min: int,
    scopes: list[str],
    bot_name: str = "Agent",
) -> dict:
    """Build an interactive card prompting user to authorize via Device Flow."""
    scope_text = "\n".join(f"• {s}" for s in scopes) if scopes else "（所有已配置权限）"

    elements = [
        {"tag": "div", "text": {"tag": "lark_md", "content": "授权后，应用将以您的身份执行相关操作。"}},
        {"tag": "div", "text": {"tag": "lark_md", "content": f"**所需权限：**\n{scope_text}"}},
        {"tag": "action", "actions": [
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "前往授权"},
                "type": "primary",
                "url": verification_uri,
            },
        ]},
        {"tag": "div", "text": {"tag": "plain_text", "content": f"授权链接将在 {expires_min} 分钟后失效"}},
    ]

    return {
        "config": {"wide_screen_mode": True, "update_multi": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"[{bot_name}] 需要您的授权才能继续"},
            "template": "blue",
        },
        "elements": elements,
    }


def build_auth_success_card(*, bot_name: str = "Agent") -> dict:
    """Build a card indicating authorization succeeded."""
    return {
        "config": {"wide_screen_mode": True, "update_multi": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"[{bot_name}] 授权成功"},
            "template": "green",
        },
        "elements": [
            {"tag": "div", "text": {"tag": "lark_md",
             "content": "您的飞书账号已成功授权，正在为您继续执行操作。\n\n如需撤销授权，可随时告诉我。"}},
        ],
    }


def build_auth_failed_card(*, reason: str = "", bot_name: str = "Agent") -> dict:
    """Build a card indicating authorization failed or expired."""
    return {
        "config": {"wide_screen_mode": True, "update_multi": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"[{bot_name}] 授权未完成"},
            "template": "yellow",
        },
        "elements": [
            {"tag": "div", "text": {"tag": "plain_text",
             "content": reason or "授权链接已过期，请重新发起授权。"}},
        ],
    }

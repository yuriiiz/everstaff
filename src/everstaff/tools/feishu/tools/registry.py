"""Feishu tool registry -- creates tool sets by category."""
from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Static catalog -- lightweight metadata that requires no credentials.
# ---------------------------------------------------------------------------

_TOOL_CATALOG: dict[str, list[dict[str, str]]] = {
    "docs": [
        {"name": "feishu_fetch_doc", "description": "获取飞书云文档内容，返回 Markdown 格式。"},
        {"name": "feishu_create_doc", "description": "创建飞书云文档。"},
        {"name": "feishu_update_doc", "description": "更新飞书云文档内容。"},
    ],
    "calendar": [
        {"name": "feishu_create_event", "description": "在飞书日历上创建日程。"},
        {"name": "feishu_list_events", "description": "查询飞书日历日程列表。"},
        {"name": "feishu_freebusy", "description": "查询飞书用户忙闲状态。"},
    ],
    "tasks": [
        {"name": "feishu_create_task", "description": "创建飞书任务。"},
        {"name": "feishu_list_tasks", "description": "查询飞书任务列表。"},
    ],
    "im": [
        {"name": "feishu_send_message", "description": "在飞书群或私聊中发送消息。"},
        {"name": "feishu_list_messages", "description": "获取飞书群聊或私聊的历史消息。"},
        {"name": "feishu_list_chats", "description": "获取用户的飞书群聊列表。"},
        {"name": "feishu_search_chats", "description": "搜索飞书群聊。"},
    ],
}


def list_all_tools(
    categories: list[str] | None = None,
) -> dict[str, list[dict[str, str]]]:
    """Return static tool metadata by category. No credentials needed."""
    if categories is None:
        return dict(_TOOL_CATALOG)
    return {k: v for k, v in _TOOL_CATALOG.items() if k in categories}


def create_feishu_tools(
    *,
    app_id: str,
    app_secret: str,
    domain: str = "feishu",
    categories: list[str] | None = None,
    auth_handler: Any = None,
    user_open_id: str = "",
    token_store: Any = None,
) -> list[Any]:
    """Create Feishu NativeTools filtered by category.

    Categories: docs, calendar, tasks, im, bitable (future)
    If categories is None, all tools are created.

    ``user_open_id`` is auto-injected from the session context so the LLM
    does not need to supply it.  When empty, tools will raise
    ``UserAuthRequiredError`` to trigger the Device Flow.
    """
    all_categories = categories or ["docs", "calendar", "tasks", "im"]
    tools: list[Any] = []

    if "docs" in all_categories:
        from everstaff.tools.feishu.tools.doc_tools import make_feishu_doc_tools
        tools.extend(make_feishu_doc_tools(app_id, app_secret, domain, auth_handler=auth_handler, user_open_id=user_open_id, token_store=token_store))

    if "calendar" in all_categories:
        from everstaff.tools.feishu.tools.calendar_tools import make_feishu_calendar_tools
        tools.extend(make_feishu_calendar_tools(app_id, app_secret, domain, auth_handler=auth_handler, user_open_id=user_open_id, token_store=token_store))

    if "tasks" in all_categories:
        from everstaff.tools.feishu.tools.task_tools import make_feishu_task_tools
        tools.extend(make_feishu_task_tools(app_id, app_secret, domain, auth_handler=auth_handler, user_open_id=user_open_id, token_store=token_store))

    if "im" in all_categories:
        from everstaff.tools.feishu.tools.im_tools import make_feishu_im_tools
        tools.extend(make_feishu_im_tools(app_id, app_secret, domain, auth_handler=auth_handler, user_open_id=user_open_id, token_store=token_store))

    return tools

"""Feishu tool registry -- creates tool sets by category."""
from __future__ import annotations

from typing import Any


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

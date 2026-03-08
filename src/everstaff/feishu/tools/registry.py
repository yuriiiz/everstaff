"""Feishu tool registry — creates tool sets by category."""
from __future__ import annotations

from typing import Any


def create_feishu_tools(
    *,
    app_id: str,
    app_secret: str,
    domain: str = "feishu",
    categories: list[str] | None = None,
) -> list[Any]:
    """Create Feishu NativeTools filtered by category.

    Categories: docs, calendar, tasks, bitable (future)
    If categories is None, all tools are created.
    """
    all_categories = categories or ["docs", "calendar", "tasks"]
    tools: list[Any] = []

    if "docs" in all_categories:
        from everstaff.feishu.tools.doc_tools import make_feishu_doc_tools
        tools.extend(make_feishu_doc_tools(app_id, app_secret, domain))

    if "calendar" in all_categories:
        from everstaff.feishu.tools.calendar_tools import make_feishu_calendar_tools
        tools.extend(make_feishu_calendar_tools(app_id, app_secret, domain))

    if "tasks" in all_categories:
        from everstaff.feishu.tools.task_tools import make_feishu_task_tools
        tools.extend(make_feishu_task_tools(app_id, app_secret, domain))

    return tools

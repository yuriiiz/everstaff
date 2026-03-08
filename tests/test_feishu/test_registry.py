"""Tests for Feishu tool registry."""
from everstaff.feishu.tools.registry import create_feishu_tools


def test_create_feishu_tools_all():
    tools = create_feishu_tools(
        app_id="app", app_secret="secret", domain="feishu",
        categories=["docs", "calendar", "tasks"],
    )
    names = [t.definition.name for t in tools]
    assert "feishu_fetch_doc" in names
    assert "feishu_create_event" in names
    assert "feishu_create_task" in names


def test_create_feishu_tools_subset():
    tools = create_feishu_tools(
        app_id="app", app_secret="secret",
        categories=["calendar"],
    )
    names = [t.definition.name for t in tools]
    assert "feishu_create_event" in names
    assert "feishu_fetch_doc" not in names

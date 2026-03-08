"""Tests for calendar tool definitions."""
from everstaff.tools.feishu.tools.calendar_tools import make_feishu_calendar_tools


def test_calendar_tools_created():
    tools = make_feishu_calendar_tools(app_id="app", app_secret="secret")
    names = [t.definition.name for t in tools]
    assert "feishu_create_event" in names
    assert "feishu_list_events" in names
    assert "feishu_freebusy" in names

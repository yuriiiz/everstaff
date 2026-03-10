"""Tests for minutes tool definitions."""
from everstaff.tools.feishu.tools.minutes_tools import make_feishu_minutes_tools


def test_minutes_tools_created():
    tools = make_feishu_minutes_tools(app_id="app", app_secret="secret")
    names = [t.definition.name for t in tools]
    assert "feishu_get_minute" in names
    assert "feishu_get_minute_transcript" in names
    assert "feishu_get_minute_statistics" in names

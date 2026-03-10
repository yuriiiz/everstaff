"""Tests for minutes tool definitions."""
from everstaff.tools.feishu.tools.minutes_tools import make_feishu_minutes_tools, _format_timestamp_ms


def test_minutes_tools_created():
    tools = make_feishu_minutes_tools(app_id="app", app_secret="secret")
    names = [t.definition.name for t in tools]
    assert "feishu_get_minute" in names
    assert "feishu_get_minute_transcript" in names
    assert "feishu_get_minute_statistics" in names
    assert "feishu_list_minutes" in names


def test_format_timestamp_ms():
    assert _format_timestamp_ms("0") == "00:00:00"
    assert _format_timestamp_ms("60000") == "00:01:00"
    assert _format_timestamp_ms("3661000") == "01:01:01"
    assert _format_timestamp_ms("invalid") == "invalid"

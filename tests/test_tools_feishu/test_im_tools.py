"""Tests for IM tool definitions."""
from everstaff.tools.feishu.tools.im_tools import make_feishu_im_tools


def test_im_tools_created():
    tools = make_feishu_im_tools(app_id="app", app_secret="secret")
    names = [t.definition.name for t in tools]
    assert "feishu_send_message" in names
    assert "feishu_list_messages" in names
    assert "feishu_list_chats" in names
    assert "feishu_search_chats" in names
    assert "feishu_search_messages" in names
    assert len(tools) == 5

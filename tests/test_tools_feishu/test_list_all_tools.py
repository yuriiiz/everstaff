from everstaff.tools.feishu.tools.registry import list_all_tools


def test_list_all_tools_returns_all_categories():
    result = list_all_tools()
    assert "im" in result
    assert "docs" in result
    assert "calendar" in result
    assert "tasks" in result


def test_list_all_tools_has_name_and_description():
    result = list_all_tools()
    for category, tools in result.items():
        for t in tools:
            assert "name" in t
            assert "description" in t
            assert t["name"].startswith("feishu_")
            assert len(t["description"]) > 0


def test_list_all_tools_filter_by_category():
    result = list_all_tools(categories=["im"])
    assert "im" in result
    assert "docs" not in result


def test_list_all_tools_filter_multiple_categories():
    result = list_all_tools(categories=["im", "docs"])
    assert "im" in result
    assert "docs" in result
    assert "calendar" not in result
    assert "tasks" not in result


def test_list_all_tools_known_tool_names():
    result = list_all_tools()
    im_names = [t["name"] for t in result["im"]]
    assert "feishu_send_message" in im_names
    assert "feishu_list_messages" in im_names
    assert "feishu_list_chats" in im_names
    assert "feishu_search_chats" in im_names

    doc_names = [t["name"] for t in result["docs"]]
    assert "feishu_fetch_doc" in doc_names
    assert "feishu_create_doc" in doc_names
    assert "feishu_update_doc" in doc_names

    cal_names = [t["name"] for t in result["calendar"]]
    assert "feishu_create_event" in cal_names
    assert "feishu_list_events" in cal_names
    assert "feishu_freebusy" in cal_names

    task_names = [t["name"] for t in result["tasks"]]
    assert "feishu_create_task" in task_names
    assert "feishu_list_tasks" in task_names


def test_list_all_tools_returns_copy():
    """Ensure the returned dict is a copy, not the internal catalog."""
    result = list_all_tools()
    result["extra"] = []
    assert "extra" not in list_all_tools()

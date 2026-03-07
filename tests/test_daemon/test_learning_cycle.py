"""Tests for the learning cycle -- insight recording via ThinkEngine."""
import pytest


def test_record_learning_insight_tool_exists():
    from everstaff.daemon.think_engine import THINK_TOOLS
    names = [t.name for t in THINK_TOOLS]
    assert "record_learning_insight" in names


def test_record_learning_insight_tool_schema():
    from everstaff.daemon.think_engine import THINK_TOOLS
    tool = next(t for t in THINK_TOOLS if t.name == "record_learning_insight")
    params = tool.parameters
    required = params.get("required", [])
    assert "category" in required
    assert "insight" in required
    assert "evidence" in required
    props = params["properties"]
    assert "category" in props
    assert "insight" in props
    assert "evidence" in props
    assert "action" in props


def test_search_memory_tool_exists():
    from everstaff.daemon.think_engine import THINK_TOOLS
    names = [t.name for t in THINK_TOOLS]
    assert "search_memory" in names


def test_old_recall_tools_removed():
    from everstaff.daemon.think_engine import THINK_TOOLS
    names = [t.name for t in THINK_TOOLS]
    assert "recall_semantic_detail" not in names
    assert "recall_recent_episodes" not in names

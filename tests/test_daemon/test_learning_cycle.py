"""Tests for the learning cycle -- insight recording via ThinkEngine."""
from everstaff.daemon.think_engine import THINK_TOOL_CLASSES, ThinkToolContext, _build_think_registry


def _tool_names() -> set[str]:
    ctx = ThinkToolContext(agent_name="t", agent_uuid="u", state=None, state_store=None, mem0=None)
    return {cls(ctx).definition.name for cls in THINK_TOOL_CLASSES}


def test_record_learning_insight_tool_exists():
    assert "record_learning_insight" in _tool_names()


def test_record_learning_insight_tool_schema():
    ctx = ThinkToolContext(agent_name="t", agent_uuid="u", state=None, state_store=None, mem0=None)
    registry = _build_think_registry(ctx)
    defns = registry.get_definitions()
    tool = next(t for t in defns if t.name == "record_learning_insight")
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
    assert "search_memory" in _tool_names()


def test_old_recall_tools_removed():
    names = _tool_names()
    assert "recall_semantic_detail" not in names
    assert "recall_recent_episodes" not in names

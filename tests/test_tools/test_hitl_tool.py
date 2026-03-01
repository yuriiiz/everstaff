def test_hitl_tool_prompt_injection():
    from everstaff.tools.hitl_tool import RequestHumanInputTool
    tool = RequestHumanInputTool()
    injection = tool.get_prompt_injection()
    assert "request_human_input" in injection
    assert "NEVER" in injection
    assert "Human Interaction Rules" in injection
    # Prompt must guide when to use vs when NOT to use
    assert "When to use" in injection
    assert "When NOT to use" in injection


def test_hitl_tool_prompt_injection_notify_only():
    from everstaff.tools.hitl_tool import RequestHumanInputTool
    tool = RequestHumanInputTool(mode="notify")
    injection = tool.get_prompt_injection()
    assert "notify-only" in injection
    assert "Human Notification Rules" in injection
    # Should NOT contain blocking guidance
    assert "NEVER" not in injection
    assert "approve_reject" not in injection


def test_hitl_tool_prompt_injection_always():
    from everstaff.tools.hitl_tool import RequestHumanInputTool
    tool = RequestHumanInputTool(mode="always")
    injection = tool.get_prompt_injection()
    assert "supervised mode" in injection
    assert "Supervised Execution Mode" in injection
    assert "approve_reject" in injection
    # Must require approval before every action
    assert "NEVER call any tool without prior approval" in injection


import pytest
from everstaff.protocols import HumanApprovalRequired


@pytest.mark.asyncio
async def test_hitl_tool_raises_list_with_single_request():
    """request_human_input must raise HumanApprovalRequired with a list."""
    from everstaff.tools.hitl_tool import RequestHumanInputTool
    tool = RequestHumanInputTool()
    with pytest.raises(HumanApprovalRequired) as exc_info:
        await tool.execute({"prompt": "Choose", "type": "approve_reject"})
    assert isinstance(exc_info.value.requests, list)
    assert len(exc_info.value.requests) == 1


@pytest.mark.asyncio
async def test_hitl_tool_default_timeout():
    """request_human_input must set timeout_seconds=86400 by default."""
    from everstaff.tools.hitl_tool import RequestHumanInputTool
    tool = RequestHumanInputTool()
    with pytest.raises(HumanApprovalRequired) as exc_info:
        await tool.execute({"prompt": "Q", "type": "provide_input"})
    assert exc_info.value.requests[0].timeout_seconds == 86400


@pytest.mark.asyncio
async def test_hitl_tool_custom_timeout():
    """request_human_input must accept custom timeout."""
    from everstaff.tools.hitl_tool import RequestHumanInputTool
    tool = RequestHumanInputTool()
    with pytest.raises(HumanApprovalRequired) as exc_info:
        await tool.execute({"prompt": "Q", "type": "provide_input", "timeout": 3600})
    assert exc_info.value.requests[0].timeout_seconds == 3600


def test_hitl_tool_definition_includes_timeout_param():
    """Tool definition must include timeout parameter."""
    from everstaff.tools.hitl_tool import RequestHumanInputTool
    tool = RequestHumanInputTool()
    params = tool.definition.parameters["properties"]
    assert "timeout" in params
    assert params["timeout"]["type"] == "integer"


@pytest.mark.asyncio
async def test_hitl_notify_only_forces_notify_type():
    """In notify mode, any type is forced to 'notify' (non-blocking)."""
    from everstaff.tools.hitl_tool import RequestHumanInputTool
    tool = RequestHumanInputTool(mode="notify")
    # Even if LLM sends approve_reject, it should NOT block
    result = await tool.execute({"prompt": "test", "type": "approve_reject"})
    assert result.content == "Notification sent"


@pytest.mark.asyncio
async def test_hitl_notify_only_no_type_required():
    """In notify mode, 'type' parameter is not required."""
    from everstaff.tools.hitl_tool import RequestHumanInputTool
    tool = RequestHumanInputTool(mode="notify")
    result = await tool.execute({"prompt": "Progress update"})
    assert result.content == "Notification sent"


def test_hitl_notify_only_definition_has_no_type_param():
    """Notify-only definition should not expose 'type' or 'options' parameters."""
    from everstaff.tools.hitl_tool import RequestHumanInputTool
    tool = RequestHumanInputTool(mode="notify")
    params = tool.definition.parameters["properties"]
    assert "type" not in params
    assert "options" not in params
    assert "prompt" in params


@pytest.mark.asyncio
async def test_hitl_always_mode_still_blocks():
    """In always mode, approve_reject still blocks (full tool, different prompt)."""
    from everstaff.tools.hitl_tool import RequestHumanInputTool
    tool = RequestHumanInputTool(mode="always")
    with pytest.raises(HumanApprovalRequired):
        await tool.execute({"prompt": "Plan to run bash", "type": "approve_reject"})


def test_hitl_always_mode_has_full_definition():
    """Always mode uses the full tool definition (all types available)."""
    from everstaff.tools.hitl_tool import RequestHumanInputTool
    tool = RequestHumanInputTool(mode="always")
    params = tool.definition.parameters["properties"]
    assert "type" in params
    assert "approve_reject" in params["type"]["enum"]


def test_hitl_invalid_mode_raises():
    """Invalid mode should raise ValueError."""
    from everstaff.tools.hitl_tool import RequestHumanInputTool
    with pytest.raises(ValueError, match="Invalid HITL mode"):
        RequestHumanInputTool(mode="invalid")

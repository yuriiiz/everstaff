"""Tests for extra_providers integration in AgentContext/Runtime."""
import pytest
from unittest.mock import MagicMock, AsyncMock

from everstaff.protocols import Message


def test_agent_context_has_extra_providers():
    from everstaff.core.context import AgentContext
    from everstaff.nulls import InMemoryStore
    from everstaff.tools.default_registry import DefaultToolRegistry
    from everstaff.tools.pipeline import ToolCallPipeline

    ctx = AgentContext(
        tool_registry=DefaultToolRegistry(),
        memory=InMemoryStore(),
        tool_pipeline=ToolCallPipeline([]),
    )
    assert ctx.extra_providers == []


def test_extra_providers_injected_in_system_prompt():
    from everstaff.core.context import AgentContext
    from everstaff.core.runtime import AgentRuntime
    from everstaff.nulls import InMemoryStore
    from everstaff.tools.default_registry import DefaultToolRegistry
    from everstaff.tools.pipeline import ToolCallPipeline

    mock_provider = MagicMock()
    mock_provider.get_prompt_injection.return_value = "[Long-term memory]\n- User likes cats"

    ctx = AgentContext(
        tool_registry=DefaultToolRegistry(),
        memory=InMemoryStore(),
        tool_pipeline=ToolCallPipeline([]),
        system_prompt="You are a helpful assistant.",
        extra_providers=[mock_provider],
    )

    mock_llm = AsyncMock()
    runtime = AgentRuntime(context=ctx, llm_client=mock_llm)
    prompt = runtime._build_system_prompt()

    assert "You are a helpful assistant." in prompt
    assert "[Long-term memory]" in prompt
    assert "User likes cats" in prompt

import pytest
from unittest.mock import AsyncMock


@pytest.mark.asyncio
async def test_agent_context_aclose_calls_mcp_provider_aclose():
    """AgentContext.aclose() must call mcp_provider.aclose()."""
    from everstaff.core.context import AgentContext
    from everstaff.nulls import InMemoryStore
    from everstaff.tools.pipeline import ToolCallPipeline
    from everstaff.tools.default_registry import DefaultToolRegistry

    mock_mcp = AsyncMock()
    mock_mcp.get_tools.return_value = []
    mock_mcp.get_prompt_injection.return_value = ""

    ctx = AgentContext(
        tool_registry=DefaultToolRegistry(),
        memory=InMemoryStore(),
        tool_pipeline=ToolCallPipeline([]),
        mcp_provider=mock_mcp,
    )

    await ctx.aclose()
    mock_mcp.aclose.assert_called_once()


@pytest.mark.asyncio
async def test_agent_context_aclose_is_safe_when_mcp_raises():
    """AgentContext.aclose() must not propagate exceptions from mcp_provider."""
    from everstaff.core.context import AgentContext
    from everstaff.nulls import InMemoryStore
    from everstaff.tools.pipeline import ToolCallPipeline
    from everstaff.tools.default_registry import DefaultToolRegistry

    mock_mcp = AsyncMock()
    mock_mcp.get_tools.return_value = []
    mock_mcp.get_prompt_injection.return_value = ""
    mock_mcp.aclose.side_effect = RuntimeError("connection already closed")

    ctx = AgentContext(
        tool_registry=DefaultToolRegistry(),
        memory=InMemoryStore(),
        tool_pipeline=ToolCallPipeline([]),
        mcp_provider=mock_mcp,
    )

    await ctx.aclose()  # must not raise

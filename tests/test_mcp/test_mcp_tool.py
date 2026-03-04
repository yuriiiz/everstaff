"""Tests for MCPTool configurable timeout."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest

from everstaff.protocols import ToolDefinition


def _make_tool(timeout_seconds: float = 30.0):
    """Create an MCPTool with a mock session."""
    from everstaff.mcp_client.tool import MCPTool

    mock_session = MagicMock()
    defn = ToolDefinition(name="test_tool", description="A test", parameters={})
    return MCPTool(
        session=mock_session,
        definition_=defn,
        timeout_seconds=timeout_seconds,
    )


@pytest.mark.asyncio
async def test_default_timeout_is_30():
    """MCPTool defaults to 30s timeout."""
    from everstaff.mcp_client.tool import MCPTool

    mock_session = MagicMock()
    defn = ToolDefinition(name="t", description="", parameters={})
    tool = MCPTool(session=mock_session, definition_=defn)
    assert tool._timeout_seconds == 30.0


@pytest.mark.asyncio
async def test_custom_timeout_stored():
    """MCPTool stores custom timeout."""
    tool = _make_tool(timeout_seconds=120.0)
    assert tool._timeout_seconds == 120.0


@pytest.mark.asyncio
async def test_timeout_used_in_execute():
    """MCPTool.execute passes configured timeout to asyncio.wait_for."""
    tool = _make_tool(timeout_seconds=90.0)

    # Mock call_tool to return a result
    mock_result = MagicMock()
    mock_result.content = [MagicMock(text="ok")]
    tool._session.call_tool = AsyncMock(return_value=mock_result)

    import unittest.mock as um
    with um.patch("asyncio.wait_for", wraps=asyncio.wait_for) as mock_wait:
        await tool.execute({"arg": "val"})
        # Verify timeout= kwarg was 90.0
        mock_wait.assert_called_once()
        _, kwargs = mock_wait.call_args
        assert kwargs["timeout"] == 90.0


@pytest.mark.asyncio
async def test_timeout_error_message_includes_configured_value():
    """Timeout error message reflects the configured timeout, not hardcoded 30s."""
    tool = _make_tool(timeout_seconds=120.0)
    tool._session.call_tool = AsyncMock(side_effect=asyncio.TimeoutError)

    import unittest.mock as um
    with um.patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
        result = await tool.execute({"arg": "val"})

    assert "120" in result.content
    assert result.is_error is True

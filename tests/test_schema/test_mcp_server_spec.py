"""Tests for MCPServerSpec multi-transport validation."""
import pytest
from pydantic import ValidationError

from everstaff.schema.agent_spec import MCPServerSpec


def test_stdio_requires_command():
    """stdio transport must have command set."""
    with pytest.raises(ValidationError, match="stdio transport requires 'command'"):
        MCPServerSpec(name="test", transport="stdio")


def test_stdio_with_command_succeeds():
    spec = MCPServerSpec(name="test", transport="stdio", command="python", args=["-m", "server"])
    assert spec.command == "python"
    assert spec.transport == "stdio"


def test_sse_requires_url():
    """sse transport must have url set."""
    with pytest.raises(ValidationError, match="sse transport requires 'url'"):
        MCPServerSpec(name="test", transport="sse")


def test_sse_with_url_succeeds():
    spec = MCPServerSpec(name="test", transport="sse", url="https://mcp.example.com/sse")
    assert spec.url == "https://mcp.example.com/sse"
    assert spec.transport == "sse"


def test_streamable_http_requires_url():
    with pytest.raises(ValidationError, match="streamable_http transport requires 'url'"):
        MCPServerSpec(name="test", transport="streamable_http")


def test_streamable_http_with_url_succeeds():
    spec = MCPServerSpec(name="test", transport="streamable_http", url="https://mcp.example.com/mcp")
    assert spec.transport == "streamable_http"


def test_headers_default_empty():
    spec = MCPServerSpec(name="test", command="python", transport="stdio")
    assert spec.headers == {}


def test_headers_set_for_remote():
    spec = MCPServerSpec(
        name="test", transport="sse", url="https://example.com/sse",
        headers={"Authorization": "Bearer tok123"},
    )
    assert spec.headers["Authorization"] == "Bearer tok123"


def test_backward_compat_stdio_command_required():
    """Existing YAML with command field must still work."""
    spec = MCPServerSpec(name="srv", command="npx", args=["-y", "@mcp/server"])
    assert spec.transport == "stdio"
    assert spec.command == "npx"


def test_timeout_default_value():
    """MCPServerSpec defaults to 30.0s timeout."""
    spec = MCPServerSpec(name="test", command="python", transport="stdio")
    assert spec.timeout == 30.0


def test_timeout_custom_value():
    """MCPServerSpec accepts a custom timeout."""
    spec = MCPServerSpec(name="test", command="python", transport="stdio", timeout=120.0)
    assert spec.timeout == 120.0


def test_timeout_in_remote_transport():
    """Timeout works for remote transports too."""
    spec = MCPServerSpec(name="test", transport="sse", url="https://example.com/sse", timeout=60.0)
    assert spec.timeout == 60.0

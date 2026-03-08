"""Tests for Feishu cloud MCP proxy."""
import pytest
from unittest.mock import MagicMock, patch

from everstaff.feishu.mcp_proxy import call_feishu_mcp


@pytest.mark.asyncio
async def test_call_feishu_mcp_success():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "jsonrpc": "2.0",
        "id": "call1",
        "result": {
            "content": [{"type": "text", "text": "# Hello\nDoc content here"}],
        },
    }

    with patch("httpx.AsyncClient.post", return_value=mock_resp):
        result = await call_feishu_mcp(
            tool_name="fetch-doc",
            args={"doc_id": "doxcnXXX"},
            uat="at_xxx",
        )
    assert result["content"][0]["text"] == "# Hello\nDoc content here"


@pytest.mark.asyncio
async def test_call_feishu_mcp_error():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "jsonrpc": "2.0",
        "id": "call1",
        "error": {"code": -32600, "message": "Invalid request"},
    }

    with patch("httpx.AsyncClient.post", return_value=mock_resp):
        with pytest.raises(RuntimeError, match="Invalid request"):
            await call_feishu_mcp(tool_name="fetch-doc", args={}, uat="at_xxx")

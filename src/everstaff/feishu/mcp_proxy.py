"""Proxy client for Feishu's cloud MCP gateway (mcp.feishu.cn/mcp)."""
from __future__ import annotations

import logging
import uuid
from typing import Any

import httpx

logger = logging.getLogger(__name__)

FEISHU_MCP_ENDPOINT = "https://mcp.feishu.cn/mcp"


async def call_feishu_mcp(
    *,
    tool_name: str,
    args: dict[str, Any],
    uat: str,
    endpoint: str = FEISHU_MCP_ENDPOINT,
) -> dict[str, Any]:
    """Call a tool on Feishu's cloud MCP gateway.

    The gateway accepts JSON-RPC 2.0 with UAT in the X-Lark-MCP-UAT header.
    """
    call_id = str(uuid.uuid4())
    body = {
        "jsonrpc": "2.0",
        "id": call_id,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": args},
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            endpoint,
            json=body,
            headers={
                "Content-Type": "application/json",
                "X-Lark-MCP-UAT": uat,
                "X-Lark-MCP-Allowed-Tools": tool_name,
            },
            timeout=30.0,
        )

    if resp.status_code != 200:
        raise RuntimeError(f"MCP HTTP {resp.status_code}: {resp.text[:500]}")

    data = resp.json()
    if "error" in data:
        err = data["error"]
        raise RuntimeError(f"MCP error {err.get('code')}: {err.get('message')}")

    return data.get("result", data)

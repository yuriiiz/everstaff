"""Feishu document tools -- proxy to cloud MCP gateway."""
from __future__ import annotations

from everstaff.tools.native import tool


def make_feishu_doc_tools(app_id: str, app_secret: str, domain: str = "feishu"):
    """Create Feishu doc NativeTools bound to a specific app."""
    from everstaff.feishu.mcp_proxy import call_feishu_mcp
    from everstaff.feishu.uat_client import call_with_uat
    from everstaff.feishu.token_store import FileTokenStore

    store = FileTokenStore()

    @tool(name="feishu_fetch_doc", description="获取飞书云文档内容，返回 Markdown 格式。")
    async def feishu_fetch_doc(doc_id: str, user_open_id: str) -> str:
        """Fetch a Feishu document's content as markdown."""
        async def _call(uat: str) -> str:
            result = await call_feishu_mcp(tool_name="fetch-doc", args={"doc_id": doc_id}, uat=uat)
            content = result.get("content", [])
            if content and content[0].get("text"):
                return content[0]["text"]
            return str(result)
        return await call_with_uat(
            user_open_id=user_open_id, app_id=app_id, app_secret=app_secret,
            domain=domain, fn=_call, token_store=store,
        )

    @tool(name="feishu_create_doc", description="创建飞书云文档。")
    async def feishu_create_doc(title: str, content: str, user_open_id: str, folder_token: str = "") -> str:
        """Create a new Feishu document."""
        async def _call(uat: str) -> str:
            args = {"title": title, "content": content}
            if folder_token:
                args["folder_token"] = folder_token
            result = await call_feishu_mcp(tool_name="create-doc", args=args, uat=uat)
            return str(result)
        return await call_with_uat(
            user_open_id=user_open_id, app_id=app_id, app_secret=app_secret,
            domain=domain, fn=_call, token_store=store,
        )

    @tool(name="feishu_update_doc", description="更新飞书云文档内容。")
    async def feishu_update_doc(doc_id: str, content: str, user_open_id: str) -> str:
        """Update a Feishu document's content."""
        async def _call(uat: str) -> str:
            result = await call_feishu_mcp(
                tool_name="update-doc", args={"doc_id": doc_id, "content": content}, uat=uat)
            return str(result)
        return await call_with_uat(
            user_open_id=user_open_id, app_id=app_id, app_secret=app_secret,
            domain=domain, fn=_call, token_store=store,
        )

    return [feishu_fetch_doc, feishu_create_doc, feishu_update_doc]

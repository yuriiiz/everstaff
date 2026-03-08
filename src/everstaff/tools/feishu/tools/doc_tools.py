"""Feishu document tools -- proxy to cloud MCP gateway."""
from __future__ import annotations

import logging

from everstaff.tools.native import tool

logger = logging.getLogger(__name__)


def make_feishu_doc_tools(app_id: str, app_secret: str, domain: str = "feishu", auth_handler=None, user_open_id: str = "", token_store=None):
    """Create Feishu doc NativeTools bound to a specific app.

    ``user_open_id`` is captured in closures so the LLM never needs to supply it.
    """
    from everstaff.tools.feishu.mcp_proxy import call_feishu_mcp
    from everstaff.tools.feishu.uat_client import call_with_uat
    from everstaff.tools.feishu.errors import UserAuthRequiredError

    store = token_store

    @tool(name="feishu_fetch_doc", description="获取飞书云文档内容，返回 Markdown 格式。")
    async def feishu_fetch_doc(doc_id: str) -> str:
        """Fetch a Feishu document's content as markdown."""
        async def _call(uat: str) -> str:
            result = await call_feishu_mcp(tool_name="fetch-doc", args={"doc_id": doc_id}, uat=uat)
            content = result.get("content", [])
            if content and content[0].get("text"):
                return content[0]["text"]
            return str(result)
        _scopes = ["docx:document:readonly"]
        try:
            return await call_with_uat(
                user_open_id=user_open_id, app_id=app_id, app_secret=app_secret,
                domain=domain, fn=_call, token_store=store, required_scopes=_scopes,
            )
        except UserAuthRequiredError as e:
            if auth_handler is None:
                raise
            from everstaff.tools.feishu.auto_auth import handle_auth_error
            e.required_scopes = e.required_scopes or _scopes
            result = await handle_auth_error(
                err=e, app_id=app_id, app_secret=app_secret, domain=domain,
                send_card_fn=auth_handler.send_card,
                update_card_fn=auth_handler.update_card,
                token_store=store,
            )
            return result.get("message", "已发送授权请求，请在飞书中完成授权后重试。")

    @tool(name="feishu_create_doc", description="创建飞书云文档。")
    async def feishu_create_doc(title: str, content: str, folder_token: str = "") -> str:
        """Create a new Feishu document."""
        async def _call(uat: str) -> str:
            args = {"title": title, "content": content}
            if folder_token:
                args["folder_token"] = folder_token
            result = await call_feishu_mcp(tool_name="create-doc", args=args, uat=uat)
            return str(result)
        _scopes = ["docx:document"]
        try:
            return await call_with_uat(
                user_open_id=user_open_id, app_id=app_id, app_secret=app_secret,
                domain=domain, fn=_call, token_store=store, required_scopes=_scopes,
            )
        except UserAuthRequiredError as e:
            if auth_handler is None:
                raise
            from everstaff.tools.feishu.auto_auth import handle_auth_error
            e.required_scopes = e.required_scopes or _scopes
            result = await handle_auth_error(
                err=e, app_id=app_id, app_secret=app_secret, domain=domain,
                send_card_fn=auth_handler.send_card,
                update_card_fn=auth_handler.update_card,
                token_store=store,
            )
            return result.get("message", "已发送授权请求，请在飞书中完成授权后重试。")

    @tool(name="feishu_update_doc", description="更新飞书云文档内容。")
    async def feishu_update_doc(doc_id: str, content: str) -> str:
        """Update a Feishu document's content."""
        async def _call(uat: str) -> str:
            result = await call_feishu_mcp(
                tool_name="update-doc", args={"doc_id": doc_id, "content": content}, uat=uat)
            return str(result)
        _scopes = ["docx:document"]
        try:
            return await call_with_uat(
                user_open_id=user_open_id, app_id=app_id, app_secret=app_secret,
                domain=domain, fn=_call, token_store=store, required_scopes=_scopes,
            )
        except UserAuthRequiredError as e:
            if auth_handler is None:
                raise
            from everstaff.tools.feishu.auto_auth import handle_auth_error
            e.required_scopes = e.required_scopes or _scopes
            result = await handle_auth_error(
                err=e, app_id=app_id, app_secret=app_secret, domain=domain,
                send_card_fn=auth_handler.send_card,
                update_card_fn=auth_handler.update_card,
                token_store=store,
            )
            return result.get("message", "已发送授权请求，请在飞书中完成授权后重试。")

    return [feishu_fetch_doc, feishu_create_doc, feishu_update_doc]

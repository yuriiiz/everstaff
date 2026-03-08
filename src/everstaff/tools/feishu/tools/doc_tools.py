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
    from everstaff.tools.feishu.tools._auth_retry import call_with_auth_retry

    store = token_store

    def _auth_kwargs(scopes: list[str]) -> dict:
        return dict(
            user_open_id=user_open_id, app_id=app_id, app_secret=app_secret,
            domain=domain, token_store=store, required_scopes=scopes,
            auth_handler=auth_handler,
        )

    @tool(name="feishu_fetch_doc", description="获取飞书云文档内容，返回 Markdown 格式。")
    async def feishu_fetch_doc(doc_id: str) -> str:
        """Fetch a Feishu document's content as markdown."""
        async def _call(uat: str) -> str:
            result = await call_feishu_mcp(tool_name="fetch-doc", args={"doc_id": doc_id}, uat=uat)
            content = result.get("content", [])
            if content and content[0].get("text"):
                return content[0]["text"]
            return str(result)

        return await call_with_auth_retry(fn=_call, **_auth_kwargs(["docx:document:readonly"]))

    @tool(name="feishu_create_doc", description="创建飞书云文档并写入 Markdown 内容。content 参数为文档正文，请务必提供。")
    async def feishu_create_doc(title: str, content: str, folder_token: str = "") -> str:
        """Create a new Feishu document and write content into it.

        Args:
            title: Document title.
            content: Markdown content to write into the document body.
            folder_token: Optional folder token to create the document in.
        """
        async def _call(uat: str) -> str:
            import json as _json

            create_args: dict = {"title": title}
            if folder_token:
                create_args["folder_token"] = folder_token
            result = await call_feishu_mcp(tool_name="create-doc", args=create_args, uat=uat)

            # Extract doc_id from MCP response
            doc_id = ""
            doc_url = ""
            if isinstance(result, dict):
                for item in result.get("content", []):
                    text = item.get("text", "")
                    if text:
                        try:
                            parsed = _json.loads(text)
                            doc_id = parsed.get("doc_id", "")
                            doc_url = parsed.get("doc_url", "")
                        except (ValueError, TypeError):
                            pass
                if not doc_id:
                    doc_id = result.get("doc_id", "")

            if not doc_id:
                return f"文档创建失败：无法获取 doc_id。原始响应: {result}"

            # Write content into the newly created document
            if content:
                try:
                    update_result = await call_feishu_mcp(
                        tool_name="update-doc",
                        args={"doc_id": doc_id, "content": content, "mode": "overwrite"},
                        uat=uat,
                    )
                    logger.info("feishu_create_doc: wrote content to %s", doc_id)
                    # Check if update-doc returned an error in its content
                    update_ok = True
                    if isinstance(update_result, dict):
                        for item in update_result.get("content", []):
                            text = item.get("text", "")
                            if text and "error" in text.lower():
                                update_ok = False
                                logger.warning("feishu_create_doc: update-doc returned error: %s", text)
                                return _json.dumps({"doc_id": doc_id, "doc_url": doc_url, "message": f"文档已创建但内容写入可能失败: {text}"}, ensure_ascii=False)
                except Exception as e:
                    logger.warning("feishu_create_doc: created doc %s but failed to write content: %s", doc_id, e, exc_info=True)
                    return _json.dumps({"doc_id": doc_id, "doc_url": doc_url, "message": f"文档已创建但内容写入失败: {e}"}, ensure_ascii=False)

            status = "文档创建成功，内容已写入" if content else "文档创建成功（无内容）"
            return _json.dumps({"doc_id": doc_id, "doc_url": doc_url, "message": status}, ensure_ascii=False)

        return await call_with_auth_retry(fn=_call, **_auth_kwargs(["docx:document"]))

    @tool(name="feishu_update_doc", description="更新飞书云文档内容。")
    async def feishu_update_doc(doc_id: str, content: str, mode: str = "overwrite") -> str:
        """Update a Feishu document's content.

        Args:
            doc_id: Document ID to update.
            content: New content in Markdown format.
            mode: Update mode: "overwrite" (replace all), "append" (add to end),
                  "replace_range", "replace_all", "insert_after", "delete_range".
        """
        async def _call(uat: str) -> str:
            result = await call_feishu_mcp(
                tool_name="update-doc", args={"doc_id": doc_id, "content": content, "mode": mode}, uat=uat)
            return str(result)

        return await call_with_auth_retry(fn=_call, **_auth_kwargs(["docx:document"]))

    return [feishu_fetch_doc, feishu_create_doc, feishu_update_doc]

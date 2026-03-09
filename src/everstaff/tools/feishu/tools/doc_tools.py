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

    @tool(name="feishu_fetch_doc", description="获取飞书云文档内容，返回 Markdown 格式。支持分页获取大文档。")
    async def feishu_fetch_doc(doc_id: str, limit: int = 0, offset: int = 0) -> str:
        """Fetch a Feishu document's content as markdown.

        Args:
            doc_id: Document ID or URL.
            limit: Max characters to return (0 = unlimited, return full document).
                   Only use when explicitly requesting pagination.
            offset: Character offset for paginated fetching (default 0).
        """
        async def _call(uat: str) -> str:
            args: dict = {"doc_id": doc_id}
            if limit > 0:
                args["limit"] = limit
            if offset > 0:
                args["offset"] = offset
            result = await call_feishu_mcp(tool_name="fetch-doc", args=args, uat=uat)
            content = result.get("content", [])
            if content and content[0].get("text"):
                return content[0]["text"]
            return str(result)

        return await call_with_auth_retry(fn=_call, **_auth_kwargs(["docx:document:readonly"]))

    @tool(name="feishu_create_doc", description="从 Markdown 创建飞书云文档。markdown 参数为文档正文，请务必提供。支持指定 wiki_node/wiki_space/folder_token（三选一互斥）。")
    async def feishu_create_doc(
        title: str, markdown: str,
        folder_token: str = "", wiki_node: str = "", wiki_space: str = "",
    ) -> str:
        """Create a new Feishu document from markdown content (single-step).

        Args:
            title: Document title.
            markdown: Markdown content for the document body.
            folder_token: Parent folder token (optional, mutually exclusive with wiki_node/wiki_space).
            wiki_node: Wiki node token or URL (optional, creates doc under this node).
            wiki_space: Wiki space ID (optional, 'my_library' for personal wiki).
        """
        async def _call(uat: str) -> str:
            args: dict = {"title": title, "markdown": markdown}
            if wiki_node:
                args["wiki_node"] = wiki_node
            elif wiki_space:
                args["wiki_space"] = wiki_space
            elif folder_token:
                args["folder_token"] = folder_token
            result = await call_feishu_mcp(tool_name="create-doc", args=args, uat=uat)
            content = result.get("content", [])
            if content and content[0].get("text"):
                return content[0]["text"]
            return str(result)

        return await call_with_auth_retry(fn=_call, **_auth_kwargs(["docx:document"]))

    @tool(name="feishu_update_doc", description="更新飞书云文档内容。支持 7 种模式：overwrite、append、replace_range、replace_all、insert_before、insert_after、delete_range。")
    async def feishu_update_doc(
        doc_id: str, markdown: str, mode: str = "overwrite",
        selection_with_ellipsis: str = "", selection_by_title: str = "",
        new_title: str = "",
    ) -> str:
        """Update a Feishu document's content.

        Args:
            doc_id: Document ID or URL.
            markdown: New content in Markdown format.
            mode: Update mode: "overwrite", "append", "replace_range", "replace_all",
                  "insert_before", "insert_after", "delete_range".
            selection_with_ellipsis: Content locator. Format: "opening...closing" to match range,
                  or exact text without "..." for precise match.
            selection_by_title: Title locator. Format: "## Section Title" to locate entire section.
            new_title: New document title (optional, plain text, 1-800 chars).
        """
        async def _call(uat: str) -> str:
            args: dict = {"doc_id": doc_id, "markdown": markdown, "mode": mode}
            if selection_with_ellipsis:
                args["selection_with_ellipsis"] = selection_with_ellipsis
            if selection_by_title:
                args["selection_by_title"] = selection_by_title
            if new_title:
                args["new_title"] = new_title
            result = await call_feishu_mcp(tool_name="update-doc", args=args, uat=uat)
            content = result.get("content", [])
            if content and content[0].get("text"):
                return content[0]["text"]
            return str(result)

        return await call_with_auth_retry(fn=_call, **_auth_kwargs(["docx:document"]))

    @tool(name="feishu_list_docs", description="获取知识空间节点下的云文档列表，或查询「我的文档库」下的文档。支持分页。")
    async def feishu_list_docs(
        doc_id: str = "", my_library: bool = False,
        page_size: int = 10, page_token: str = "",
    ) -> str:
        """List documents under a wiki node or user's My Library.

        Args:
            doc_id: Wiki document URL to list children of. Required when my_library=False.
            my_library: If True, list docs from user's My Library (doc_id can be omitted).
            page_size: Number of results per page (1-50, default 10).
            page_token: Pagination token for next page.
        """
        async def _call(uat: str) -> str:
            args: dict = {}
            if my_library:
                args["my_library"] = True
            if doc_id:
                args["doc_id"] = doc_id
            if page_size != 10:
                args["page_size"] = min(max(page_size, 1), 50)
            if page_token:
                args["page_token"] = page_token
            result = await call_feishu_mcp(tool_name="list-docs", args=args, uat=uat)
            content = result.get("content", [])
            if content and content[0].get("text"):
                return content[0]["text"]
            return str(result)

        return await call_with_auth_retry(fn=_call, **_auth_kwargs(["docx:document:readonly", "wiki:wiki:readonly"]))

    return [feishu_fetch_doc, feishu_create_doc, feishu_update_doc, feishu_list_docs]

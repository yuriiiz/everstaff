"""Feishu IM (instant messaging) tools — MCP proxy + direct OAPI calls."""
from __future__ import annotations

import logging

from everstaff.tools.native import tool

logger = logging.getLogger(__name__)


def make_feishu_im_tools(app_id: str, app_secret: str, domain: str = "feishu", auth_handler=None, user_open_id: str = "", token_store=None):
    """Create Feishu IM NativeTools.

    ``user_open_id`` is captured in closures so the LLM never needs to supply it.
    """
    from everstaff.tools.feishu.mcp_proxy import call_feishu_mcp
    from everstaff.tools.feishu.tools._auth_retry import call_with_auth_retry
    import httpx

    store = token_store
    api_base = "https://open.feishu.cn" if domain != "lark" else "https://open.larksuite.com"

    def _auth_kwargs(scopes: list[str]) -> dict:
        return dict(
            user_open_id=user_open_id, app_id=app_id, app_secret=app_secret,
            domain=domain, token_store=store, required_scopes=scopes,
            auth_handler=auth_handler,
        )

    @tool(name="feishu_send_message", description="在飞书群或私聊中发送消息。支持普通消息和消息卡片，支持回复和话题回复。")
    async def feishu_send_message(
        receive_id: str, content: str,
        receive_id_type: str = "chat",
        msg_type: str = "normal",
        reply_to_message_id: str = "",
        reply_in_thread: bool = False,
    ) -> str:
        """Send a message in Feishu via MCP gateway.

        Args:
            receive_id: Target ID (chat_id for group, openId for DM).
            content: Message content. For normal: Markdown subset. For interactive: card JSON.
            receive_id_type: Type of receive_id: "chat" (group) or "user" (DM).
            msg_type: Message type: "normal" (markdown) or "interactive" (card).
            reply_to_message_id: Message ID to reply to (optional). Triggers reply mode.
            reply_in_thread: Whether to reply as a thread (only effective with reply_to_message_id).
        """
        async def _call(uat: str) -> str:
            args: dict = {
                "receive_id": receive_id,
                "receive_id_type": receive_id_type,
                "msg_type": msg_type,
                "content": content,
            }
            if reply_to_message_id:
                args["reply_to_message_id"] = reply_to_message_id
            if reply_in_thread:
                args["reply_in_thread"] = True
            result = await call_feishu_mcp(tool_name="send-message", args=args, uat=uat)
            result_content = result.get("content", [])
            if result_content and result_content[0].get("text"):
                return result_content[0]["text"]
            return str(result)

        return await call_with_auth_retry(fn=_call, **_auth_kwargs(["im:message"]))

    @tool(name="feishu_list_messages", description="获取飞书群聊或私聊的历史消息。")
    async def feishu_list_messages(
        container_id: str,
        start_time: str = "", end_time: str = "", page_size: int = 20,
        page_token: str = "",
    ) -> str:
        """List messages from a chat.

        Args:
            container_id: Chat ID (oc_xxx).
            start_time: Optional start time (Unix timestamp in seconds).
            end_time: Optional end time (Unix timestamp in seconds).
            page_size: Number of messages to return (max 50).
            page_token: Pagination token from a previous response (for fetching the next page).
        """
        async def _call(uat: str) -> str:
            params: dict = {
                "container_id_type": "chat",
                "container_id": container_id,
                "page_size": min(page_size, 50),
            }
            if start_time:
                params["start_time"] = start_time
            if end_time:
                params["end_time"] = end_time
            if page_token:
                params["page_token"] = page_token
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{api_base}/open-apis/im/v1/messages",
                    params=params,
                    headers={"Authorization": f"Bearer {uat}"},
                )
            return resp.text

        return await call_with_auth_retry(fn=_call, **_auth_kwargs(["im:message:readonly"]))

    @tool(name="feishu_list_chats", description="获取用户的飞书群聊列表。")
    async def feishu_list_chats(page_size: int = 20) -> str:
        """List user's chats.

        Args:
            page_size: Number of chats to return (max 100).
        """
        async def _call(uat: str) -> str:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{api_base}/open-apis/im/v1/chats",
                    params={"page_size": min(page_size, 100)},
                    headers={"Authorization": f"Bearer {uat}"},
                )
            return resp.text

        return await call_with_auth_retry(fn=_call, **_auth_kwargs(["im:chat:readonly"]))

    @tool(name="feishu_search_chats", description="搜索飞书群聊。")
    async def feishu_search_chats(query: str, page_size: int = 20) -> str:
        """Search for chats by keyword.

        Args:
            query: Search keyword.
            page_size: Number of results (max 100).
        """
        async def _call(uat: str) -> str:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{api_base}/open-apis/im/v1/chats/search",
                    params={"query": query, "page_size": min(page_size, 100)},
                    headers={"Authorization": f"Bearer {uat}"},
                )
            return resp.text

        return await call_with_auth_retry(fn=_call, **_auth_kwargs(["im:chat:readonly"]))

    @tool(name="feishu_search_messages", description="搜索飞书消息，支持按关键词、发送者、时间、类型等条件过滤。")
    async def feishu_search_messages(
        query: str = "",
        chat_type: str = "",
        sender_ids: str = "",
        mention_ids: str = "",
        start_time: str = "",
        end_time: str = "",
        relative_time: str = "",
        message_type: str = "",
        sender_type: str = "user",
        page_size: int = 20,
        page_token: str = "",
    ) -> str:
        """Search Feishu messages via MCP gateway.

        Args:
            query: Search keyword (matches message content). Empty string for no content filter.
            chat_type: Chat type filter: "group" or "p2p". Empty for all.
            sender_ids: Comma-separated sender open_ids.
            mention_ids: Comma-separated mentioned user open_ids.
            start_time: Start time in ISO 8601 format (e.g. "2024-01-01T00:00:00+08:00").
            end_time: End time in ISO 8601 format.
            relative_time: Relative time range. Semantic: today, yesterday, this_week, last_week,
                          this_month, last_month. Or: last_30_minutes, last_1_hour, last_3_days.
            message_type: Message type filter: "file", "image", or "media". Empty for all.
            sender_type: Sender type: "user", "bot", or "all" (default "user").
            page_size: Results per page (1-50, default 20).
            page_token: Pagination token for next page.
        """
        async def _call(uat: str) -> str:
            args: dict = {}
            if query:
                args["query"] = query
            if chat_type:
                args["chat_type"] = chat_type
            if sender_ids:
                args["sender_ids"] = [s.strip() for s in sender_ids.split(",")]
            if mention_ids:
                args["mention_ids"] = [s.strip() for s in mention_ids.split(",")]
            if start_time:
                args["start_time"] = start_time
            if end_time:
                args["end_time"] = end_time
            if relative_time:
                args["relative_time"] = relative_time
            if message_type:
                args["message_type"] = message_type
            if sender_type != "user":
                args["sender_type"] = sender_type
            if page_size != 20:
                args["page_size"] = min(max(page_size, 1), 50)
            if page_token:
                args["page_token"] = page_token
            result = await call_feishu_mcp(tool_name="search-messages", args=args, uat=uat)
            result_content = result.get("content", [])
            if result_content and result_content[0].get("text"):
                return result_content[0]["text"]
            return str(result)

        return await call_with_auth_retry(fn=_call, **_auth_kwargs(["im:message:readonly"]))

    return [feishu_send_message, feishu_list_messages, feishu_list_chats, feishu_search_chats, feishu_search_messages]

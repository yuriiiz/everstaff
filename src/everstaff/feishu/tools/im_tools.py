"""Feishu IM (instant messaging) tools — direct OAPI calls."""
from __future__ import annotations

import logging

from everstaff.tools.native import tool

logger = logging.getLogger(__name__)


def make_feishu_im_tools(app_id: str, app_secret: str, domain: str = "feishu", auth_handler=None, user_open_id: str = "", token_store=None):
    """Create Feishu IM NativeTools.

    ``user_open_id`` is captured in closures so the LLM never needs to supply it.
    """
    from everstaff.feishu.uat_client import call_with_uat
    from everstaff.feishu.errors import UserAuthRequiredError
    import httpx

    store = token_store
    api_base = "https://open.feishu.cn" if domain != "lark" else "https://open.larksuite.com"

    @tool(name="feishu_send_message", description="在飞书群或私聊中发送消息。")
    async def feishu_send_message(
        receive_id: str, content: str,
        receive_id_type: str = "chat_id", msg_type: str = "text",
    ) -> str:
        """Send a message in Feishu.

        Args:
            receive_id: Target ID (chat_id for group, open_id for DM).
            content: Message content. For text: JSON string like {"text":"hello"}. For interactive: card JSON.
            receive_id_type: Type of receive_id: "chat_id", "open_id", or "user_id".
            msg_type: Message type: "text", "interactive", "image", etc.
        """
        async def _call(uat: str) -> str:
            body = {
                "receive_id": receive_id,
                "msg_type": msg_type,
                "content": content,
            }
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{api_base}/open-apis/im/v1/messages?receive_id_type={receive_id_type}",
                    json=body,
                    headers={"Authorization": f"Bearer {uat}", "Content-Type": "application/json"},
                )
            return resp.text

        try:
            return await call_with_uat(
                user_open_id=user_open_id, app_id=app_id, app_secret=app_secret,
                domain=domain, fn=_call, token_store=store,
            )
        except UserAuthRequiredError as e:
            if auth_handler is None:
                raise
            from everstaff.feishu.auto_auth import handle_auth_error
            e.required_scopes = e.required_scopes or ["im:message"]
            result = await handle_auth_error(
                err=e, app_id=app_id, app_secret=app_secret, domain=domain,
                send_card_fn=auth_handler.send_card,
                update_card_fn=auth_handler.update_card,
                token_store=store,
            )
            return result.get("message", "已发送授权请求，请在飞书中完成授权后重试。")

    @tool(name="feishu_list_messages", description="获取飞书群聊或私聊的历史消息。")
    async def feishu_list_messages(
        container_id: str,
        start_time: str = "", end_time: str = "", page_size: int = 20,
    ) -> str:
        """List messages from a chat.

        Args:
            container_id: Chat ID (oc_xxx).
            start_time: Optional start time (Unix timestamp in seconds).
            end_time: Optional end time (Unix timestamp in seconds).
            page_size: Number of messages to return (max 50).
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
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{api_base}/open-apis/im/v1/messages",
                    params=params,
                    headers={"Authorization": f"Bearer {uat}"},
                )
            return resp.text

        try:
            return await call_with_uat(
                user_open_id=user_open_id, app_id=app_id, app_secret=app_secret,
                domain=domain, fn=_call, token_store=store,
            )
        except UserAuthRequiredError as e:
            if auth_handler is None:
                raise
            from everstaff.feishu.auto_auth import handle_auth_error
            e.required_scopes = e.required_scopes or ["im:message:readonly"]
            result = await handle_auth_error(
                err=e, app_id=app_id, app_secret=app_secret, domain=domain,
                send_card_fn=auth_handler.send_card,
                update_card_fn=auth_handler.update_card,
                token_store=store,
            )
            return result.get("message", "已发送授权请求，请在飞书中完成授权后重试。")

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

        try:
            return await call_with_uat(
                user_open_id=user_open_id, app_id=app_id, app_secret=app_secret,
                domain=domain, fn=_call, token_store=store,
            )
        except UserAuthRequiredError as e:
            if auth_handler is None:
                raise
            from everstaff.feishu.auto_auth import handle_auth_error
            e.required_scopes = e.required_scopes or ["im:chat:readonly"]
            result = await handle_auth_error(
                err=e, app_id=app_id, app_secret=app_secret, domain=domain,
                send_card_fn=auth_handler.send_card,
                update_card_fn=auth_handler.update_card,
                token_store=store,
            )
            return result.get("message", "已发送授权请求，请在飞书中完成授权后重试。")

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

        try:
            return await call_with_uat(
                user_open_id=user_open_id, app_id=app_id, app_secret=app_secret,
                domain=domain, fn=_call, token_store=store,
            )
        except UserAuthRequiredError as e:
            if auth_handler is None:
                raise
            from everstaff.feishu.auto_auth import handle_auth_error
            e.required_scopes = e.required_scopes or ["im:chat:readonly"]
            result = await handle_auth_error(
                err=e, app_id=app_id, app_secret=app_secret, domain=domain,
                send_card_fn=auth_handler.send_card,
                update_card_fn=auth_handler.update_card,
                token_store=store,
            )
            return result.get("message", "已发送授权请求，请在飞书中完成授权后重试。")

    return [feishu_send_message, feishu_list_messages, feishu_list_chats, feishu_search_chats]

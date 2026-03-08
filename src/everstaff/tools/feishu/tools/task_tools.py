"""Feishu task tools -- direct OAPI calls."""
from __future__ import annotations

import logging

from everstaff.tools.native import tool

logger = logging.getLogger(__name__)


def make_feishu_task_tools(app_id: str, app_secret: str, domain: str = "feishu", auth_handler=None, user_open_id: str = "", token_store=None):
    """Create Feishu task NativeTools.

    ``user_open_id`` is captured in closures so the LLM never needs to supply it.
    """
    from everstaff.tools.feishu.uat_client import call_with_uat
    from everstaff.tools.feishu.errors import UserAuthRequiredError
    import httpx

    store = token_store
    api_base = "https://open.feishu.cn" if domain != "lark" else "https://open.larksuite.com"

    @tool(name="feishu_create_task", description="创建飞书任务。")
    async def feishu_create_task(
        summary: str, due: str = "", description: str = "",
    ) -> str:
        """Create a Feishu task.

        Args:
            summary: Task title.
            due: Optional due date (ISO 8601).
            description: Optional task description.
        """
        async def _call(uat: str) -> str:
            body: dict = {"summary": summary}
            if due:
                body["due"] = {"timestamp": due}
            if description:
                body["description"] = description
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{api_base}/open-apis/task/v2/tasks",
                    json=body,
                    headers={"Authorization": f"Bearer {uat}", "Content-Type": "application/json"},
                )
            return resp.text

        _scopes = ["task:task"]
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

    @tool(name="feishu_list_tasks", description="查询飞书任务列表。")
    async def feishu_list_tasks() -> str:
        """List user's tasks."""
        async def _call(uat: str) -> str:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{api_base}/open-apis/task/v2/tasks",
                    headers={"Authorization": f"Bearer {uat}"},
                )
            return resp.text

        _scopes = ["task:task:readonly"]
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

    return [feishu_create_task, feishu_list_tasks]

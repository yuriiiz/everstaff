"""Feishu task tools -- direct OAPI calls."""
from __future__ import annotations

import logging

from everstaff.tools.native import tool

logger = logging.getLogger(__name__)


def make_feishu_task_tools(app_id: str, app_secret: str, domain: str = "feishu", auth_handler=None, user_open_id: str = "", token_store=None, base_scopes: list[str] | None = None, include_offline_access: bool = True):
    """Create Feishu task NativeTools.

    ``user_open_id`` is captured in closures so the LLM never needs to supply it.
    """
    from everstaff.tools.feishu.tools._auth_retry import call_with_auth_retry
    import httpx

    store = token_store
    api_base = "https://open.feishu.cn" if domain != "lark" else "https://open.larksuite.com"

    def _auth_kwargs(scopes: list[str]) -> dict:
        return dict(
            user_open_id=user_open_id, app_id=app_id, app_secret=app_secret,
            domain=domain, token_store=store, required_scopes=scopes,
            auth_handler=auth_handler, base_scopes=base_scopes, include_offline_access=include_offline_access,
        )

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

        return await call_with_auth_retry(fn=_call, **_auth_kwargs(["task:task:write"]))

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

        return await call_with_auth_retry(fn=_call, **_auth_kwargs(["task:task:readonly"]))

    return [feishu_create_task, feishu_list_tasks]

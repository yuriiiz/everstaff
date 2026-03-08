"""Feishu task tools — direct OAPI calls."""
from __future__ import annotations

from everstaff.tools.native import tool


def make_feishu_task_tools(app_id: str, app_secret: str, domain: str = "feishu"):
    """Create Feishu task NativeTools."""
    from everstaff.feishu.uat_client import call_with_uat
    from everstaff.feishu.token_store import FileTokenStore
    import httpx

    store = FileTokenStore()
    api_base = "https://open.feishu.cn" if domain != "lark" else "https://open.larksuite.com"

    @tool(name="feishu_create_task", description="创建飞书任务。")
    async def feishu_create_task(
        summary: str, user_open_id: str, due: str = "", description: str = "",
    ) -> str:
        """Create a Feishu task.

        Args:
            summary: Task title.
            user_open_id: User's open_id.
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

        return await call_with_uat(
            user_open_id=user_open_id, app_id=app_id, app_secret=app_secret,
            domain=domain, fn=_call, token_store=store,
        )

    @tool(name="feishu_list_tasks", description="查询飞书任务列表。")
    async def feishu_list_tasks(user_open_id: str) -> str:
        """List user's tasks.

        Args:
            user_open_id: User's open_id.
        """
        async def _call(uat: str) -> str:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{api_base}/open-apis/task/v2/tasks",
                    headers={"Authorization": f"Bearer {uat}"},
                )
            return resp.text

        return await call_with_uat(
            user_open_id=user_open_id, app_id=app_id, app_secret=app_secret,
            domain=domain, fn=_call, token_store=store,
        )

    return [feishu_create_task, feishu_list_tasks]

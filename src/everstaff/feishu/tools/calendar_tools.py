"""Feishu calendar tools — direct OAPI calls via lark-oapi SDK."""
from __future__ import annotations

from everstaff.tools.native import tool


def make_feishu_calendar_tools(app_id: str, app_secret: str, domain: str = "feishu"):
    """Create Feishu calendar NativeTools."""
    from everstaff.feishu.uat_client import call_with_uat
    from everstaff.feishu.token_store import FileTokenStore
    import httpx

    store = FileTokenStore()
    api_base = "https://open.feishu.cn" if domain != "lark" else "https://open.larksuite.com"

    @tool(name="feishu_create_event", description="在飞书日历上创建日程。")
    async def feishu_create_event(
        summary: str, start_time: str, end_time: str, user_open_id: str,
        description: str = "", attendees: str = "",
    ) -> str:
        """Create a calendar event.

        Args:
            summary: Event title.
            start_time: ISO 8601 start time (e.g. 2026-03-10T14:00:00+08:00).
            end_time: ISO 8601 end time.
            user_open_id: User's open_id.
            description: Optional event description.
            attendees: Comma-separated open_ids of attendees.
        """
        async def _call(uat: str) -> str:
            body: dict = {
                "summary": summary,
                "start_time": {"timestamp": start_time},
                "end_time": {"timestamp": end_time},
            }
            if description:
                body["description"] = description
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{api_base}/open-apis/calendar/v4/calendars/primary/events",
                    json=body,
                    headers={"Authorization": f"Bearer {uat}", "Content-Type": "application/json"},
                )
            return resp.text

        return await call_with_uat(
            user_open_id=user_open_id, app_id=app_id, app_secret=app_secret,
            domain=domain, fn=_call, token_store=store,
        )

    @tool(name="feishu_list_events", description="查询飞书日历日程列表。")
    async def feishu_list_events(
        user_open_id: str, start_time: str = "", end_time: str = "",
    ) -> str:
        """List calendar events.

        Args:
            user_open_id: User's open_id.
            start_time: Optional ISO 8601 start time filter.
            end_time: Optional ISO 8601 end time filter.
        """
        async def _call(uat: str) -> str:
            params: dict = {}
            if start_time:
                params["start_time"] = start_time
            if end_time:
                params["end_time"] = end_time
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{api_base}/open-apis/calendar/v4/calendars/primary/events",
                    params=params,
                    headers={"Authorization": f"Bearer {uat}"},
                )
            return resp.text

        return await call_with_uat(
            user_open_id=user_open_id, app_id=app_id, app_secret=app_secret,
            domain=domain, fn=_call, token_store=store,
        )

    @tool(name="feishu_freebusy", description="查询飞书用户忙闲状态。")
    async def feishu_freebusy(
        user_open_id: str, start_time: str, end_time: str,
    ) -> str:
        """Query free/busy status for a time range.

        Args:
            user_open_id: User's open_id.
            start_time: ISO 8601 start time.
            end_time: ISO 8601 end time.
        """
        async def _call(uat: str) -> str:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{api_base}/open-apis/calendar/v4/freebusy/list",
                    json={"time_min": start_time, "time_max": end_time},
                    headers={"Authorization": f"Bearer {uat}", "Content-Type": "application/json"},
                )
            return resp.text

        return await call_with_uat(
            user_open_id=user_open_id, app_id=app_id, app_secret=app_secret,
            domain=domain, fn=_call, token_store=store,
        )

    return [feishu_create_event, feishu_list_events, feishu_freebusy]

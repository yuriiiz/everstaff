"""Feishu calendar tools -- direct OAPI calls via lark-oapi SDK."""
from __future__ import annotations

import logging

from everstaff.tools.native import tool

logger = logging.getLogger(__name__)


def make_feishu_calendar_tools(app_id: str, app_secret: str, domain: str = "feishu", auth_handler=None, user_open_id: str = "", token_store=None):
    """Create Feishu calendar NativeTools.

    ``user_open_id`` is captured in closures so the LLM never needs to supply it.
    """
    from everstaff.tools.feishu.tools._auth_retry import call_with_auth_retry
    import httpx

    store = token_store
    api_base = "https://open.feishu.cn" if domain != "lark" else "https://open.larksuite.com"

    # Cache the primary calendar ID per token to avoid repeated lookups
    _primary_calendar_cache: dict[str, str] = {}

    async def _get_primary_calendar_id(uat: str) -> str:
        """Get the user's primary calendar ID via API, with caching."""
        if uat in _primary_calendar_cache:
            return _primary_calendar_cache[uat]

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{api_base}/open-apis/calendar/v4/calendars/primary",
                headers={"Authorization": f"Bearer {uat}"},
            )
        data = resp.json()
        cal_id = ""
        if data.get("code") == 0:
            cal = data.get("data", {}).get("calendars", [])
            if cal:
                cal_id = cal[0].get("calendar", {}).get("calendar_id", "")
        if not cal_id:
            # Fallback: list calendars and find the primary one
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{api_base}/open-apis/calendar/v4/calendars",
                    headers={"Authorization": f"Bearer {uat}"},
                )
            data = resp.json()
            for item in data.get("data", {}).get("calendar_list", []):
                if item.get("role") == "owner" or item.get("type") == "primary":
                    cal_id = item.get("calendar_id", "")
                    break
            if not cal_id:
                # Last resort: use first calendar
                cals = data.get("data", {}).get("calendar_list", [])
                if cals:
                    cal_id = cals[0].get("calendar_id", "")

        if cal_id:
            _primary_calendar_cache[uat] = cal_id
        return cal_id

    def _auth_kwargs(scopes: list[str]) -> dict:
        return dict(
            user_open_id=user_open_id, app_id=app_id, app_secret=app_secret,
            domain=domain, token_store=store, required_scopes=scopes,
            auth_handler=auth_handler,
        )

    @tool(name="feishu_create_event", description="在飞书日历上创建日程。")
    async def feishu_create_event(
        summary: str, start_time: str, end_time: str,
        description: str = "", attendees: str = "",
    ) -> str:
        """Create a calendar event.

        Args:
            summary: Event title.
            start_time: Unix timestamp string (seconds since epoch).
            end_time: Unix timestamp string (seconds since epoch).
            description: Optional event description.
            attendees: Comma-separated open_ids of attendees.
        """
        async def _call(uat: str) -> str:
            cal_id = await _get_primary_calendar_id(uat)
            if not cal_id:
                return '{"error": "无法获取用户主日历 ID，请确认日历权限已授权"}'

            body: dict = {
                "summary": summary,
                "start_time": {"timestamp": start_time},
                "end_time": {"timestamp": end_time},
            }
            if description:
                body["description"] = description
            if attendees:
                body["attendees"] = [
                    {"type": "user", "user_id": uid.strip()}
                    for uid in attendees.split(",") if uid.strip()
                ]
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{api_base}/open-apis/calendar/v4/calendars/{cal_id}/events",
                    json=body,
                    headers={"Authorization": f"Bearer {uat}", "Content-Type": "application/json"},
                )
            return resp.text

        return await call_with_auth_retry(fn=_call, **_auth_kwargs(["calendar:calendar"]))

    @tool(name="feishu_list_events", description="查询飞书日历日程列表。")
    async def feishu_list_events(
        start_time: str = "", end_time: str = "",
    ) -> str:
        """List calendar events.

        Args:
            start_time: Optional Unix timestamp string (seconds since epoch) for start filter.
            end_time: Optional Unix timestamp string (seconds since epoch) for end filter.
        """
        async def _call(uat: str) -> str:
            cal_id = await _get_primary_calendar_id(uat)
            if not cal_id:
                return '{"error": "无法获取用户主日历 ID，请确认日历权限已授权"}'

            params: dict = {}
            if start_time:
                params["start_time"] = start_time
            if end_time:
                params["end_time"] = end_time
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{api_base}/open-apis/calendar/v4/calendars/{cal_id}/events",
                    params=params,
                    headers={"Authorization": f"Bearer {uat}"},
                )
            return resp.text

        return await call_with_auth_retry(fn=_call, **_auth_kwargs(["calendar:calendar:readonly"]))

    @tool(name="feishu_freebusy", description="查询飞书用户忙闲状态。")
    async def feishu_freebusy(
        start_time: str, end_time: str,
    ) -> str:
        """Query free/busy status for a time range.

        Args:
            start_time: Unix timestamp string (seconds since epoch).
            end_time: Unix timestamp string (seconds since epoch).
        """
        async def _call(uat: str) -> str:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{api_base}/open-apis/calendar/v4/freebusy/list",
                    json={"time_min": start_time, "time_max": end_time},
                    headers={"Authorization": f"Bearer {uat}", "Content-Type": "application/json"},
                )
            return resp.text

        return await call_with_auth_retry(fn=_call, **_auth_kwargs(["calendar:calendar:readonly"]))

    return [feishu_create_event, feishu_list_events, feishu_freebusy]

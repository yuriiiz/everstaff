"""Feishu calendar tools -- direct OAPI calls via lark-oapi SDK."""
from __future__ import annotations

import logging

from everstaff.tools.native import tool

logger = logging.getLogger(__name__)


def make_feishu_calendar_tools(app_id: str, app_secret: str, domain: str = "feishu", auth_handler=None):
    """Create Feishu calendar NativeTools."""
    from everstaff.feishu.uat_client import call_with_uat
    from everstaff.feishu.token_store import FileTokenStore
    from everstaff.feishu.errors import UserAuthRequiredError
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
            start_time: Unix timestamp string (seconds since epoch).
            end_time: Unix timestamp string (seconds since epoch).
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
            if attendees:
                body["attendees"] = [
                    {"type": "user", "user_id": uid.strip()}
                    for uid in attendees.split(",") if uid.strip()
                ]
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{api_base}/open-apis/calendar/v4/calendars/primary/events",
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
            e.required_scopes = e.required_scopes or ["calendar:calendar"]
            result = await handle_auth_error(
                err=e, app_id=app_id, app_secret=app_secret, domain=domain,
                send_card_fn=auth_handler.send_card,
                update_card_fn=auth_handler.update_card,
                token_store=store,
            )
            return result.get("message", "已发送授权请求，请在飞书中完成授权后重试。")

    @tool(name="feishu_list_events", description="查询飞书日历日程列表。")
    async def feishu_list_events(
        user_open_id: str, start_time: str = "", end_time: str = "",
    ) -> str:
        """List calendar events.

        Args:
            user_open_id: User's open_id.
            start_time: Optional Unix timestamp string (seconds since epoch) for start filter.
            end_time: Optional Unix timestamp string (seconds since epoch) for end filter.
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

        try:
            return await call_with_uat(
                user_open_id=user_open_id, app_id=app_id, app_secret=app_secret,
                domain=domain, fn=_call, token_store=store,
            )
        except UserAuthRequiredError as e:
            if auth_handler is None:
                raise
            from everstaff.feishu.auto_auth import handle_auth_error
            e.required_scopes = e.required_scopes or ["calendar:calendar:readonly"]
            result = await handle_auth_error(
                err=e, app_id=app_id, app_secret=app_secret, domain=domain,
                send_card_fn=auth_handler.send_card,
                update_card_fn=auth_handler.update_card,
                token_store=store,
            )
            return result.get("message", "已发送授权请求，请在飞书中完成授权后重试。")

    @tool(name="feishu_freebusy", description="查询飞书用户忙闲状态。")
    async def feishu_freebusy(
        user_open_id: str, start_time: str, end_time: str,
    ) -> str:
        """Query free/busy status for a time range.

        Args:
            user_open_id: User's open_id.
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

        try:
            return await call_with_uat(
                user_open_id=user_open_id, app_id=app_id, app_secret=app_secret,
                domain=domain, fn=_call, token_store=store,
            )
        except UserAuthRequiredError as e:
            if auth_handler is None:
                raise
            from everstaff.feishu.auto_auth import handle_auth_error
            e.required_scopes = e.required_scopes or ["calendar:calendar:readonly"]
            result = await handle_auth_error(
                err=e, app_id=app_id, app_secret=app_secret, domain=domain,
                send_card_fn=auth_handler.send_card,
                update_card_fn=auth_handler.update_card,
                token_store=store,
            )
            return result.get("message", "已发送授权请求，请在飞书中完成授权后重试。")

    return [feishu_create_event, feishu_list_events, feishu_freebusy]

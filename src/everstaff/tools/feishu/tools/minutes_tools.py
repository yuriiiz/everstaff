"""Feishu minutes (妙记) tools -- direct OAPI calls."""
from __future__ import annotations

import logging

from everstaff.tools.native import tool

logger = logging.getLogger(__name__)


def _format_timestamp_ms(ms_str: str) -> str:
    """Convert milliseconds string to HH:MM:SS format."""
    try:
        total_sec = int(ms_str) // 1000
    except (ValueError, TypeError):
        return ms_str
    h, remainder = divmod(total_sec, 3600)
    m, s = divmod(remainder, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def make_feishu_minutes_tools(
    app_id: str,
    app_secret: str,
    domain: str = "feishu",
    auth_handler=None,
    user_open_id: str = "",
    token_store=None,
    base_scopes: list[str] | None = None,
    include_offline_access: bool = True,
):
    """Create Feishu minutes NativeTools.

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

    @tool(name="feishu_get_minute", description="获取飞书妙记信息，包括标题、时长、创建者、链接等。")
    async def feishu_get_minute(minute_token: str, user_id_type: str = "open_id") -> str:
        """Get minutes meta info.

        Args:
            minute_token: Unique minutes identifier, usually the last 24 chars of the minutes URL.
            user_id_type: User ID type: open_id (default), union_id, or user_id.
        """
        async def _call(uat: str) -> str:
            params: dict = {}
            if user_id_type != "open_id":
                params["user_id_type"] = user_id_type
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{api_base}/open-apis/minutes/v1/minutes/{minute_token}",
                    params=params,
                    headers={"Authorization": f"Bearer {uat}"},
                )
            return resp.text

        return await call_with_auth_retry(fn=_call, **_auth_kwargs(["minutes:minutes"]))

    @tool(name="feishu_get_minute_transcript", description="获取飞书妙记的转写内容（文字记录）。默认返回按说话人格式化的文本，设置 raw=true 返回原始 JSON。")
    async def feishu_get_minute_transcript(minute_token: str, raw: bool = False) -> str:
        """Get minutes transcript content.

        Args:
            minute_token: Unique minutes identifier, usually the last 24 chars of the minutes URL.
            raw: If True, return raw JSON response. Default False returns formatted text.
        """
        async def _call(uat: str) -> str:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{api_base}/open-apis/minutes/v1/minutes/{minute_token}/transcripts",
                    headers={"Authorization": f"Bearer {uat}"},
                )
            if raw:
                return resp.text
            data = resp.json()
            if data.get("code") != 0:
                return resp.text
            transcript = data.get("data", {}).get("transcript", [])
            if not transcript:
                return resp.text
            lines = []
            for seg in transcript:
                speaker = seg.get("speaker", {}).get("user_name", "Unknown")
                start = _format_timestamp_ms(seg.get("start_time", "0"))
                text = seg.get("content", "")
                lines.append(f"[{speaker} {start}] {text}")
            return "\n".join(lines)

        return await call_with_auth_retry(fn=_call, **_auth_kwargs(["minutes:minutes"]))

    @tool(name="feishu_get_minute_statistics", description="获取飞书妙记的观看统计信息。")
    async def feishu_get_minute_statistics(minute_token: str) -> str:
        """Get minutes view statistics.

        Args:
            minute_token: Unique minutes identifier, usually the last 24 chars of the minutes URL.
        """
        async def _call(uat: str) -> str:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{api_base}/open-apis/minutes/v1/minutes/{minute_token}/statistics",
                    headers={"Authorization": f"Bearer {uat}"},
                )
            return resp.text

        return await call_with_auth_retry(fn=_call, **_auth_kwargs(["minutes:minutes"]))

    return [feishu_get_minute, feishu_get_minute_transcript, feishu_get_minute_statistics]

"""Feishu minutes (妙记) tools -- direct OAPI calls."""
from __future__ import annotations

import json
import logging
import re

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

    @tool(name="feishu_get_minute", description="获取飞书妙记（会议纪要/会议录制的AI转写）的基本信息，包括标题、时长、创建者、链接等。妙记是飞书视频会议的录制转写产物。")
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

    @tool(name="feishu_get_minute_transcript", description="获取飞书妙记（会议纪要）的转写内容（文字记录）。妙记是飞书视频会议的录制转写产物。默认返回按说话人格式化的文本，设置 raw=true 返回原始 JSON。")
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

    @tool(name="feishu_get_minute_statistics", description="获取飞书妙记（会议纪要）的观看统计信息。")
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

    # Regex to extract minute_token from Feishu/Lark minutes URLs
    _MINUTE_URL_RE = re.compile(r"(?:feishu\.cn|larkoffice\.com|larksuite\.com|feishu-pre\.cn)/minutes/([A-Za-z0-9_-]{20,})")

    @tool(name="feishu_list_minutes", description="搜索并列出飞书妙记（会议纪要/会议录制转写）。通过搜索消息中的妙记链接来发现妙记，返回妙记列表（标题、时长、创建时间、链接）。当用户想查找会议纪要、会议记录、会议转写时使用此工具。")
    async def feishu_list_minutes(
        query: str = "",
        page_size: int = 20,
    ) -> str:
        """List Feishu minutes by searching for minutes links in messages.

        Args:
            query: Optional keyword to narrow search (e.g. meeting topic). Empty for all minutes.
            page_size: Max number of minutes to return (default 20).
        """
        from everstaff.tools.feishu.mcp_proxy import call_feishu_mcp

        async def _call(uat: str) -> str:
            # Step 1: Search messages for minutes URLs via MCP proxy
            search_args: dict = {"query": query if query else "feishu.cn/minutes"}
            search_args["page_size"] = min(max(page_size, 1), 50)
            result = await call_feishu_mcp(tool_name="search-messages", args=search_args, uat=uat)
            search_text = ""
            result_content = result.get("content", [])
            if result_content and result_content[0].get("text"):
                search_text = result_content[0]["text"]
            else:
                search_text = str(result)

            # Step 2: Extract unique minute_tokens from search results
            tokens_seen: set[str] = set()
            for match in _MINUTE_URL_RE.finditer(search_text):
                tokens_seen.add(match.group(1))

            if not tokens_seen:
                return json.dumps({"minutes": [], "message": "未找到妙记链接"}, ensure_ascii=False)

            # Step 3: Fetch meta for each unique token
            minutes_list = []
            async with httpx.AsyncClient(timeout=30) as client:
                for token in list(tokens_seen)[:page_size]:
                    try:
                        meta_resp = await client.get(
                            f"{api_base}/open-apis/minutes/v1/minutes/{token}",
                            headers={"Authorization": f"Bearer {uat}"},
                        )
                        meta = meta_resp.json()
                        if meta.get("code") == 0:
                            minute = meta.get("data", {}).get("minute", {})
                            minutes_list.append({
                                "token": minute.get("token", token),
                                "title": minute.get("title", ""),
                                "duration": _format_timestamp_ms(minute.get("duration", "0")),
                                "create_time": minute.get("create_time", ""),
                                "url": minute.get("url", ""),
                                "owner_id": minute.get("owner_id", ""),
                            })
                    except Exception as e:
                        logger.warning("Failed to fetch minute meta for %s: %s", token, e)

            # Sort by create_time descending (newest first)
            minutes_list.sort(key=lambda m: m.get("create_time", "0"), reverse=True)

            return json.dumps({"minutes": minutes_list, "total": len(minutes_list)}, ensure_ascii=False, indent=2)

        return await call_with_auth_retry(fn=_call, **_auth_kwargs(["search:message", "minutes:minutes"]))

    return [feishu_get_minute, feishu_get_minute_transcript, feishu_get_minute_statistics, feishu_list_minutes]

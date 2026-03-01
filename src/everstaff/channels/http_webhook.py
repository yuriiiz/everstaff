"""HTTP webhook HITL channel — POSTs JSON payload to a configured URL."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from everstaff.protocols import HitlRequest, HitlResolution

logger = logging.getLogger(__name__)

try:
    import aiohttp
except ImportError:
    aiohttp = None  # type: ignore[assignment]


class HttpWebhookChannel:
    """
    Sends HITL requests as JSON POST to a configured webhook URL.
    Resolution is handled externally via the API's /hitl endpoint.
    ``on_resolved`` is a no-op.
    """

    def __init__(self, url: str, headers: dict[str, str] | None = None) -> None:
        self._url = url
        self._headers = dict(headers or {})

    async def send_request(self, session_id: str, request: "HitlRequest") -> None:
        if not self._url:
            logger.warning("HttpWebhookChannel: no URL configured, skipping")
            return
        if aiohttp is None:
            raise RuntimeError("aiohttp is required for HttpWebhookChannel")
        payload = {
            "hitl_id": request.hitl_id,
            "session_id": session_id,
            "type": request.type,
            "prompt": request.prompt,
            "context": request.context,
            "options": request.options,
            "timeout_seconds": request.timeout_seconds,
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self._url, json=payload, headers=self._headers) as resp:
                    if resp.status >= 400:
                        logger.warning(
                            "HttpWebhookChannel: POST to %s returned HTTP %s",
                            self._url, resp.status,
                        )
                    else:
                        logger.info(
                            "HttpWebhookChannel: sent HITL request %s to %s",
                            request.hitl_id, self._url,
                        )
        except Exception as exc:
            logger.error("HttpWebhookChannel.send_request failed: %s", exc)

    async def on_resolved(self, hitl_id: str, resolution: "HitlResolution") -> None:
        """No-op: webhook callers resolve via the API endpoint."""

    async def start(self) -> None:
        logger.info("HttpWebhookChannel ready — target: %s", self._url)

    async def stop(self) -> None:
        pass

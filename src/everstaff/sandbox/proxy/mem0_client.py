"""ProxyMem0Client — forwards mem0 operations over IPC to orchestrator."""
from __future__ import annotations

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from everstaff.sandbox.ipc.channel import IpcChannel


class ProxyMem0Client:
    """Mem0Client replacement that proxies add/search over IPC."""

    def __init__(self, channel: "IpcChannel") -> None:
        self._channel = channel

    async def add(self, messages: list[dict], **scope: Any) -> Any:
        params: dict[str, Any] = {"messages": messages}
        params.update(scope)
        return await self._channel.send_request("mem0.add", params)

    async def search(self, query: str, *, top_k: int | None = None, **scope: Any) -> list[dict]:
        params: dict[str, Any] = {"query": query, "top_k": top_k}
        params.update(scope)
        return await self._channel.send_request("mem0.search", params)

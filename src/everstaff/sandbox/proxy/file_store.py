"""ProxyFileStore — forwards FileStore operations over IPC channel."""
from __future__ import annotations

import base64
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from everstaff.sandbox.ipc.channel import IpcChannel


class ProxyFileStore:
    """FileStore that forwards all operations over IPC to orchestrator."""

    def __init__(self, channel: "IpcChannel") -> None:
        self._channel = channel

    async def read(self, path: str) -> bytes:
        result = await self._channel.send_request("file.read", {"path": path})
        return base64.b64decode(result.get("data", ""))

    async def write(self, path: str, data: bytes) -> None:
        await self._channel.send_request("file.write", {
            "path": path,
            "data": base64.b64encode(data).decode(),
        })

    async def exists(self, path: str) -> bool:
        result = await self._channel.send_request("file.exists", {"path": path})
        return result.get("exists", False)

    async def delete(self, path: str) -> None:
        await self._channel.send_request("file.delete", {"path": path})

    async def list(self, prefix: str) -> list[str]:
        result = await self._channel.send_request("file.list", {"prefix": prefix})
        return result.get("files", [])

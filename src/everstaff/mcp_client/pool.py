"""McpConnectionPool — cross-session connection pool with idle timeout cleanup."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from .connection import MCPConnection

if TYPE_CHECKING:
    from everstaff.schema.agent_spec import MCPServerSpec
    from everstaff.mcp_client.tool import MCPTool

logger = logging.getLogger(__name__)


def _spec_key(spec: "MCPServerSpec") -> str:
    """Generate a stable cache key from an MCPServerSpec."""
    if spec.transport == "stdio":
        return f"stdio:{spec.command}:{':'.join(spec.args)}"
    return f"{spec.transport}:{spec.url}"


class _PoolEntry:
    __slots__ = ("conn", "tools", "key", "idle_since")

    def __init__(self, conn: MCPConnection, tools: list["MCPTool"], key: str):
        self.conn = conn
        self.tools = tools
        self.key = key
        self.idle_since: float | None = None


class McpConnectionPool:
    """Reusable MCP connection pool with idle timeout cleanup.

    Connections are keyed by server spec fingerprint (transport + command/url).
    Active connections are tracked; released connections go to idle pool.
    Idle connections are cleaned up after ``idle_timeout`` seconds.
    """

    def __init__(self, idle_timeout: float = 300.0) -> None:
        self._idle_timeout = idle_timeout
        self._active: dict[int, _PoolEntry] = {}
        self._idle: dict[str, list[_PoolEntry]] = {}
        self._cleanup_task: asyncio.Task | None = None

    @property
    def active_count(self) -> int:
        return len(self._active)

    @property
    def idle_count(self) -> int:
        return sum(len(entries) for entries in self._idle.values())

    async def acquire(self, spec: "MCPServerSpec") -> tuple[MCPConnection, list["MCPTool"]]:
        """Get a connection for the given spec, reusing an idle one if available."""
        key = _spec_key(spec)

        if key in self._idle and self._idle[key]:
            entry = self._idle[key].pop()
            if not self._idle[key]:
                del self._idle[key]
            entry.idle_since = None
            self._active[id(entry.conn)] = entry
            logger.debug("Reusing pooled MCP connection for '%s'", spec.name)
            return entry.conn, entry.tools

        conn = MCPConnection(spec)
        tools = await conn.connect()
        entry = _PoolEntry(conn=conn, tools=tools, key=key)
        self._active[id(conn)] = entry
        logger.debug("Created new MCP connection for '%s' (%d tools)", spec.name, len(tools))
        return conn, tools

    async def release(self, conn: MCPConnection) -> None:
        """Return a connection to the idle pool."""
        entry = self._active.pop(id(conn), None)
        if entry is None:
            return
        entry.idle_since = time.monotonic()
        self._idle.setdefault(entry.key, []).append(entry)

    async def cleanup_idle(self) -> None:
        """Disconnect connections that have been idle longer than timeout."""
        now = time.monotonic()
        for key in list(self._idle.keys()):
            entries = self._idle[key]
            still_alive = []
            for entry in entries:
                if entry.idle_since is not None and (now - entry.idle_since) > self._idle_timeout:
                    logger.debug("Closing idle MCP connection (key=%s)", key)
                    await entry.conn.disconnect()
                else:
                    still_alive.append(entry)
            if still_alive:
                self._idle[key] = still_alive
            else:
                del self._idle[key]

    def start_cleanup_loop(self) -> None:
        """Start periodic background cleanup of idle connections."""
        if self._cleanup_task is not None:
            return

        async def _loop():
            while True:
                await asyncio.sleep(self._idle_timeout / 2)
                try:
                    await self.cleanup_idle()
                except Exception:
                    logger.exception("Error during MCP pool idle cleanup")

        self._cleanup_task = asyncio.create_task(_loop())

    async def close(self) -> None:
        """Disconnect all connections (idle + active) and stop cleanup loop."""
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
            self._cleanup_task = None

        for entries in self._idle.values():
            for entry in entries:
                await entry.conn.disconnect()
        self._idle.clear()

        for entry in self._active.values():
            await entry.conn.disconnect()
        self._active.clear()

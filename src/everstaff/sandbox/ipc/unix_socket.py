"""Unix socket IPC channel and server."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Awaitable

from everstaff.sandbox.ipc.channel import IpcChannel
from everstaff.sandbox.ipc.protocol import (
    make_request,
    make_notification,
    make_response,
    parse_message,
    JsonRpcRequest,
    JsonRpcNotification,
    JsonRpcResponse,
)

logger = logging.getLogger(__name__)


class UnixSocketChannel(IpcChannel):
    """IPC channel client over Unix domain socket."""

    def __init__(self) -> None:
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._pending: dict[int | str, asyncio.Future] = {}
        self._push_handlers: dict[str, Callable[[dict[str, Any]], Awaitable[None]]] = {}
        self._listen_task: asyncio.Task | None = None
        self._next_id_counter: int = 0
        self._connected: bool = False

    def _next_id(self) -> int:
        self._next_id_counter += 1
        return self._next_id_counter

    async def connect(self, address: str) -> None:
        self._reader, self._writer = await asyncio.open_unix_connection(address)
        self._connected = True
        self._listen_task = asyncio.create_task(self._listen_loop())

    async def send_request(self, method: str, params: dict[str, Any]) -> Any:
        if not self._connected:
            raise ConnectionError("Not connected")
        msg_id = self._next_id()
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[msg_id] = future
        msg = make_request(method, params, msg_id)
        await self._send_raw(msg.model_dump_json())
        try:
            return await future
        finally:
            self._pending.pop(msg_id, None)

    async def send_notification(self, method: str, params: dict[str, Any]) -> None:
        if not self._connected:
            raise ConnectionError("Not connected")
        msg = make_notification(method, params)
        await self._send_raw(msg.model_dump_json())

    def on_push(self, method: str, handler: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
        self._push_handlers[method] = handler

    async def close(self) -> None:
        self._connected = False
        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except (asyncio.CancelledError, Exception):
                pass
            self._listen_task = None
        if self._writer:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass
        self._reader = None
        self._writer = None
        # Fail all pending requests
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(ConnectionError("Channel closed"))
        self._pending.clear()

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def _send_raw(self, data: str) -> None:
        assert self._writer is not None
        self._writer.write(data.encode() + b"\n")
        await self._writer.drain()

    async def _listen_loop(self) -> None:
        assert self._reader is not None
        try:
            while self._connected:
                line = await self._reader.readline()
                if not line:
                    break
                try:
                    msg = parse_message(line.decode().strip())
                except Exception:
                    logger.warning("Failed to parse IPC message: %s", line[:200])
                    continue

                if isinstance(msg, JsonRpcResponse):
                    fut = self._pending.get(msg.id)
                    if fut and not fut.done():
                        if msg.error:
                            fut.set_exception(
                                RuntimeError(f"IPC error {msg.error.code}: {msg.error.message}")
                            )
                        else:
                            fut.set_result(msg.result)
                elif isinstance(msg, (JsonRpcRequest, JsonRpcNotification)):
                    handler = self._push_handlers.get(msg.method)
                    if handler:
                        asyncio.create_task(handler(msg.params))
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("IPC listen loop error")
        finally:
            self._connected = False


class UnixSocketServer:
    """IPC server over Unix domain socket.

    handler signature: async def handler(method, params, send_response)
    For notifications (no id), send_response is a no-op.
    """

    def __init__(
        self,
        socket_path: str,
        handler: Callable[..., Awaitable[None]],
    ) -> None:
        self._socket_path = socket_path
        self._handler = handler
        self._server: asyncio.AbstractServer | None = None
        self._clients: list[asyncio.StreamWriter] = []

    async def start(self) -> None:
        self._server = await asyncio.start_unix_server(
            self._handle_client, self._socket_path
        )

    async def stop(self) -> None:
        for writer in self._clients:
            writer.close()
        self._clients.clear()
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def push_to_all(self, method: str, params: dict[str, Any]) -> None:
        """Push a notification to all connected clients."""
        msg = make_notification(method, params)
        raw = msg.model_dump_json().encode() + b"\n"
        for writer in list(self._clients):
            try:
                writer.write(raw)
                await writer.drain()
            except Exception:
                pass

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._clients.append(writer)
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                try:
                    msg = parse_message(line.decode().strip())
                except Exception:
                    continue

                if isinstance(msg, (JsonRpcRequest, JsonRpcNotification)):
                    msg_id = getattr(msg, "id", None)

                    async def send_response(result: Any, _id=msg_id, _w=writer) -> None:
                        if _id is None:
                            return  # notification — no response
                        resp = make_response(result, _id)
                        _w.write(resp.model_dump_json().encode() + b"\n")
                        await _w.drain()

                    await self._handler(msg.method, msg.params, send_response)
        except (asyncio.CancelledError, ConnectionError):
            pass
        except Exception:
            logger.exception("IPC client handler error")
        finally:
            if writer in self._clients:
                self._clients.remove(writer)
            writer.close()

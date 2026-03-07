"""End-to-end integration test: sandbox proxy -> IPC -> server handler -> mock impl."""
import asyncio
import os
import pytest
import tempfile
from unittest.mock import AsyncMock, MagicMock

from everstaff.core.secret_store import SecretStore
from everstaff.protocols import Message
from everstaff.sandbox.ipc.unix_socket import UnixSocketChannel, UnixSocketServer
from everstaff.sandbox.ipc.server_handler import IpcServerHandler
from everstaff.sandbox.proxy.memory_store import ProxyMemoryStore
from everstaff.sandbox.proxy.tracer import ProxyTracer
from everstaff.sandbox.proxy.file_store import ProxyFileStore
from everstaff.sandbox.token_store import EphemeralTokenStore


def _short_socket_path() -> str:
    d = tempfile.mkdtemp(prefix="es-", dir="/tmp")
    return os.path.join(d, "t.sock")


@pytest.mark.asyncio
class TestEndToEndIpc:
    async def _setup(self):
        """Set up server + client connected over unix socket."""
        socket_path = _short_socket_path()

        memory = MagicMock()
        memory.save = AsyncMock()
        memory.load = AsyncMock(return_value=[Message(role="user", content="test input")])
        memory.load_stats = AsyncMock(return_value=None)

        tracer = MagicMock()
        tracer.on_event = MagicMock()

        file_store = MagicMock()
        file_store.read = AsyncMock(return_value=b"file-content")
        file_store.write = AsyncMock()
        file_store.exists = AsyncMock(return_value=False)

        token_store = EphemeralTokenStore()
        secret_store = SecretStore({"LLM_API_KEY": "sk-123", "DB_URL": "postgres://..."})

        handler = IpcServerHandler(
            memory_store=memory,
            tracer=tracer,
            file_store=file_store,
            token_store=token_store,
            secret_store=secret_store,
        )

        async def server_handler(method, params, send_response):
            result = await handler.handle(method, params)
            await send_response(result)

        server = UnixSocketServer(socket_path, server_handler)
        await server.start()

        client = UnixSocketChannel()
        await client.connect(socket_path)

        return server, client, handler, token_store, memory, tracer

    async def test_auth_and_secret_delivery(self):
        server, client, handler, token_store, _, _ = await self._setup()
        try:
            token = token_store.create("session-1")
            result = await client.send_request("auth", {"token": token})
            assert result["secrets"]["LLM_API_KEY"] == "sk-123"
            assert result["secrets"]["DB_URL"] == "postgres://..."
        finally:
            await client.close()
            await server.stop()

    async def test_proxy_memory_save_and_load(self):
        server, client, _, token_store, memory, _ = await self._setup()
        try:
            proxy = ProxyMemoryStore(client)

            # Save
            await proxy.save("s1", [Message(role="user", content="hello")], status="running")
            memory.save.assert_called_once()

            # Load
            msgs = await proxy.load("s1")
            assert len(msgs) == 1
            assert msgs[0].content == "test input"
        finally:
            await client.close()
            await server.stop()

    async def test_proxy_tracer_event(self):
        server, client, _, _, _, tracer = await self._setup()
        try:
            from everstaff.protocols import TraceEvent
            proxy = ProxyTracer(client)
            proxy.on_event(TraceEvent(
                kind="session_start", session_id="s1", data={"agent": "test"}
            ))
            await asyncio.sleep(0.1)  # let fire-and-forget complete
            tracer.on_event.assert_called_once()
        finally:
            await client.close()
            await server.stop()

    async def test_proxy_file_exists(self):
        server, client, _, _, _, _ = await self._setup()
        try:
            proxy = ProxyFileStore(client)
            exists = await proxy.exists("s1/cancel.signal")
            assert exists is False  # mock returns False
        finally:
            await client.close()
            await server.stop()

    async def test_cancel_push(self):
        server, client, _, _, _, _ = await self._setup()
        cancelled = asyncio.Event()

        async def on_cancel(params):
            cancelled.set()

        client.on_push("cancel", on_cancel)
        await asyncio.sleep(0.05)  # let listen loop start

        try:
            await server.push_to_all("cancel", {"session_id": "s1"})
            await asyncio.wait_for(cancelled.wait(), timeout=2.0)
            assert cancelled.is_set()
        finally:
            await client.close()
            await server.stop()

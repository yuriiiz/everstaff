"""Tests for UnixSocketChannel — client/server integration."""
import asyncio
import os
import pytest
import tempfile

from everstaff.sandbox.ipc.unix_socket import UnixSocketChannel, UnixSocketServer


def _short_socket_path() -> str:
    """Create a short socket path to avoid macOS 104-char AF_UNIX limit."""
    d = tempfile.mkdtemp(prefix="es-", dir="/tmp")
    return os.path.join(d, "t.sock")


@pytest.mark.asyncio
class TestUnixSocketChannel:
    async def test_connect_and_request(self):
        socket_path = _short_socket_path()

        async def handler(method, params, send_response):
            await send_response({"echo": params})

        server = UnixSocketServer(socket_path, handler)
        await server.start()
        try:
            client = UnixSocketChannel()
            await client.connect(socket_path)
            try:
                result = await client.send_request("test.echo", {"msg": "hello"})
                assert result == {"echo": {"msg": "hello"}}
            finally:
                await client.close()
        finally:
            await server.stop()

    async def test_notification_no_response(self):
        socket_path = _short_socket_path()
        received = []

        async def handler(method, params, send_response):
            received.append((method, params))

        server = UnixSocketServer(socket_path, handler)
        await server.start()
        try:
            client = UnixSocketChannel()
            await client.connect(socket_path)
            try:
                await client.send_notification("tracer.event", {"kind": "test"})
                await asyncio.sleep(0.05)
                assert len(received) == 1
                assert received[0] == ("tracer.event", {"kind": "test"})
            finally:
                await client.close()
        finally:
            await server.stop()

    async def test_server_push(self):
        socket_path = _short_socket_path()
        push_received = asyncio.Event()
        push_data = {}

        async def handler(method, params, send_response):
            await send_response({"ok": True})

        server = UnixSocketServer(socket_path, handler)
        await server.start()
        try:
            client = UnixSocketChannel()
            await client.connect(socket_path)

            async def on_cancel(params):
                push_data.update(params)
                push_received.set()

            client.on_push("cancel", on_cancel)
            await asyncio.sleep(0.05)  # let listen loop start

            try:
                await server.push_to_all("cancel", {"session_id": "s1"})
                await asyncio.wait_for(push_received.wait(), timeout=2.0)
                assert push_data == {"session_id": "s1"}
            finally:
                await client.close()
        finally:
            await server.stop()

    async def test_multiple_concurrent_requests(self):
        socket_path = _short_socket_path()

        async def handler(method, params, send_response):
            delay = params.get("delay", 0)
            if delay:
                await asyncio.sleep(delay)
            await send_response({"method": method, "params": params})

        server = UnixSocketServer(socket_path, handler)
        await server.start()
        try:
            client = UnixSocketChannel()
            await client.connect(socket_path)
            try:
                r1, r2 = await asyncio.gather(
                    client.send_request("fast", {"delay": 0, "id": 1}),
                    client.send_request("slow", {"delay": 0.05, "id": 2}),
                )
                assert r1["params"]["id"] == 1
                assert r2["params"]["id"] == 2
            finally:
                await client.close()
        finally:
            await server.stop()

    async def test_is_connected(self):
        socket_path = _short_socket_path()

        async def handler(method, params, send_response):
            await send_response({})

        server = UnixSocketServer(socket_path, handler)
        await server.start()
        try:
            client = UnixSocketChannel()
            assert not client.is_connected
            await client.connect(socket_path)
            assert client.is_connected
            await client.close()
            assert not client.is_connected
        finally:
            await server.stop()

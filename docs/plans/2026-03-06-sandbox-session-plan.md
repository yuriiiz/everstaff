# Session-in-Sandbox Implementation Plan (Phase 3-5)

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Move entire AgentRuntime into isolated sandbox processes with proxy adapters for all orchestrator infrastructure, communicating over an abstract IPC channel.

**Architecture:** Abstract IPC channel with JSON-RPC 2.0 protocol. Sandbox-side proxy adapters (ProxyMemoryStore, ProxyTracer, ProxyFileStore) implement existing Protocol interfaces. Orchestrator-side IPC server routes messages to real implementations. Secret delivery happens as the first IPC message after ephemeral token auth.

**Tech Stack:** Python asyncio, Unix domain sockets, JSON-RPC 2.0, Pydantic models

**Test runner:** `uv run pytest`

---

## Task 0: SandboxResult Timestamps

**Files:**
- Modify: `src/everstaff/sandbox/models.py:13-18`
- Modify: `src/everstaff/sandbox/process_sandbox.py:84-123`
- Modify: `tests/test_sandbox/test_process_sandbox.py`

**Step 1: Write the failing test**

Add to `tests/test_sandbox/test_process_sandbox.py`:

```python
async def test_execute_bash_timestamps(self, tmp_path):
    store = SecretStore()
    sandbox = ProcessSandbox(workdir=tmp_path, secret_store=store)
    await sandbox.start("test-session")
    try:
        cmd = SandboxCommand(type="bash", payload={"command": "echo hello"})
        result = await sandbox.execute(cmd)
        assert result.success
        assert result.started_at is not None
        assert result.finished_at is not None
        assert result.finished_at >= result.started_at
    finally:
        await sandbox.stop()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_sandbox/test_process_sandbox.py::TestProcessSandbox::test_execute_bash_timestamps -v`
Expected: FAIL — `started_at` and `finished_at` are None (not set yet)

**Step 3: Implement**

In `src/everstaff/sandbox/models.py`, add fields to SandboxResult:

```python
class SandboxResult(BaseModel):
    """Result returned from sandbox command execution."""
    success: bool
    output: str = ""
    exit_code: int = 0
    error: str = ""
    started_at: float | None = None
    finished_at: float | None = None
```

In `src/everstaff/sandbox/process_sandbox.py`, update `_exec_bash` to record times:

```python
async def _exec_bash(self, payload: dict) -> SandboxResult:
    cmd = payload.get("command", "")
    timeout = min(max(payload.get("timeout", 300), 1), 3600)
    started_at = time.monotonic()

    try:
        process = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self._workdir,
            env=self._subprocess_env,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=float(timeout)
            )
        except asyncio.TimeoutError:
            try:
                process.terminate()
                await process.wait()
            except Exception:
                pass
            return SandboxResult(
                success=False,
                exit_code=-1,
                error=f"Timeout: command exceeded {timeout} seconds",
                started_at=started_at,
                finished_at=time.monotonic(),
            )

        output = stdout.decode(errors="replace")
        err = stderr.decode(errors="replace")
        if err:
            output += f"\n{err}"

        return SandboxResult(
            success=process.returncode == 0,
            output=output.strip(),
            exit_code=process.returncode or 0,
            started_at=started_at,
            finished_at=time.monotonic(),
        )
    except Exception as e:
        return SandboxResult(
            success=False,
            error=str(e),
            started_at=started_at,
            finished_at=time.monotonic(),
        )
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_sandbox/ -v`
Expected: All pass including the new timestamp test

**Step 5: Commit**

```bash
git add src/everstaff/sandbox/models.py src/everstaff/sandbox/process_sandbox.py tests/test_sandbox/test_process_sandbox.py
git commit -m "feat: add started_at/finished_at timestamps to SandboxResult"
```

---

## Task 1: JSON-RPC Protocol Models

**Files:**
- Create: `src/everstaff/sandbox/ipc/__init__.py`
- Create: `src/everstaff/sandbox/ipc/protocol.py`
- Create: `tests/test_sandbox/test_ipc/__init__.py`
- Create: `tests/test_sandbox/test_ipc/test_protocol.py`

**Step 1: Write the failing tests**

Create `tests/test_sandbox/test_ipc/__init__.py` (empty).

Create `tests/test_sandbox/test_ipc/test_protocol.py`:

```python
"""Tests for JSON-RPC protocol models."""
import pytest
from everstaff.sandbox.ipc.protocol import (
    JsonRpcRequest,
    JsonRpcNotification,
    JsonRpcResponse,
    JsonRpcError,
    make_request,
    make_notification,
    make_response,
    make_error_response,
    parse_message,
)


class TestJsonRpcModels:
    def test_make_request(self):
        msg = make_request("memory.save", {"session_id": "s1"}, msg_id=1)
        assert msg.jsonrpc == "2.0"
        assert msg.method == "memory.save"
        assert msg.params == {"session_id": "s1"}
        assert msg.id == 1

    def test_make_notification(self):
        msg = make_notification("tracer.event", {"kind": "llm_start"})
        assert msg.jsonrpc == "2.0"
        assert msg.method == "tracer.event"
        assert msg.id is None

    def test_make_response(self):
        msg = make_response({"messages": []}, msg_id=1)
        assert msg.result == {"messages": []}
        assert msg.id == 1
        assert msg.error is None

    def test_make_error_response(self):
        msg = make_error_response(-32601, "Method not found", msg_id=1)
        assert msg.error is not None
        assert msg.error.code == -32601
        assert msg.error.message == "Method not found"
        assert msg.id == 1

    def test_parse_request(self):
        raw = '{"jsonrpc":"2.0","method":"auth","params":{"token":"abc"},"id":1}'
        msg = parse_message(raw)
        assert isinstance(msg, JsonRpcRequest)
        assert msg.method == "auth"

    def test_parse_notification(self):
        raw = '{"jsonrpc":"2.0","method":"tracer.event","params":{"kind":"x"}}'
        msg = parse_message(raw)
        assert isinstance(msg, JsonRpcNotification)
        assert msg.method == "tracer.event"

    def test_parse_response(self):
        raw = '{"jsonrpc":"2.0","result":{"ok":true},"id":1}'
        msg = parse_message(raw)
        assert isinstance(msg, JsonRpcResponse)
        assert msg.result == {"ok": True}

    def test_serialization_roundtrip(self):
        req = make_request("test.method", {"key": "val"}, msg_id=42)
        raw = req.model_dump_json()
        parsed = parse_message(raw)
        assert isinstance(parsed, JsonRpcRequest)
        assert parsed.method == "test.method"
        assert parsed.id == 42
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_sandbox/test_ipc/test_protocol.py -v`
Expected: FAIL — module not found

**Step 3: Implement**

Create `src/everstaff/sandbox/ipc/__init__.py`:
```python
"""IPC channel abstraction for sandbox communication."""
```

Create `src/everstaff/sandbox/ipc/protocol.py`:

```python
"""JSON-RPC 2.0 message models for sandbox IPC."""
from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel


class JsonRpcError(BaseModel):
    code: int
    message: str
    data: Any | None = None


class JsonRpcRequest(BaseModel):
    jsonrpc: str = "2.0"
    method: str
    params: dict[str, Any] = {}
    id: int | str | None = None


class JsonRpcNotification(BaseModel):
    """Like JsonRpcRequest but id is always None (no response expected)."""
    jsonrpc: str = "2.0"
    method: str
    params: dict[str, Any] = {}
    id: None = None


class JsonRpcResponse(BaseModel):
    jsonrpc: str = "2.0"
    result: Any | None = None
    error: JsonRpcError | None = None
    id: int | str | None = None


def make_request(method: str, params: dict[str, Any], msg_id: int | str) -> JsonRpcRequest:
    return JsonRpcRequest(method=method, params=params, id=msg_id)


def make_notification(method: str, params: dict[str, Any]) -> JsonRpcNotification:
    return JsonRpcNotification(method=method, params=params)


def make_response(result: Any, msg_id: int | str) -> JsonRpcResponse:
    return JsonRpcResponse(result=result, id=msg_id)


def make_error_response(code: int, message: str, msg_id: int | str | None = None, data: Any = None) -> JsonRpcResponse:
    return JsonRpcResponse(error=JsonRpcError(code=code, message=message, data=data), id=msg_id)


def parse_message(raw: str) -> JsonRpcRequest | JsonRpcNotification | JsonRpcResponse:
    """Parse a JSON-RPC message from raw JSON string."""
    data = json.loads(raw)
    if "method" in data:
        if data.get("id") is not None:
            return JsonRpcRequest.model_validate(data)
        return JsonRpcNotification.model_validate(data)
    return JsonRpcResponse.model_validate(data)
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_sandbox/test_ipc/test_protocol.py -v`
Expected: All 8 tests PASS

**Step 5: Commit**

```bash
git add src/everstaff/sandbox/ipc/ tests/test_sandbox/test_ipc/
git commit -m "feat: add JSON-RPC 2.0 protocol models for sandbox IPC"
```

---

## Task 2: IPC Channel Abstraction + EphemeralTokenStore

**Files:**
- Create: `src/everstaff/sandbox/ipc/channel.py`
- Create: `src/everstaff/sandbox/token_store.py`
- Create: `tests/test_sandbox/test_token_store.py`

**Step 1: Write the failing tests**

Create `tests/test_sandbox/test_token_store.py`:

```python
"""Tests for EphemeralTokenStore."""
import time
import pytest
from everstaff.sandbox.token_store import EphemeralTokenStore


class TestEphemeralTokenStore:
    def test_create_and_validate(self):
        store = EphemeralTokenStore()
        token = store.create("session-1", ttl_seconds=30)
        assert isinstance(token, str)
        assert len(token) > 16
        result = store.validate_and_consume(token)
        assert result == "session-1"

    def test_single_use(self):
        store = EphemeralTokenStore()
        token = store.create("session-1")
        assert store.validate_and_consume(token) == "session-1"
        assert store.validate_and_consume(token) is None  # already consumed

    def test_invalid_token(self):
        store = EphemeralTokenStore()
        assert store.validate_and_consume("nonexistent") is None

    def test_expired_token(self):
        store = EphemeralTokenStore()
        token = store.create("session-1", ttl_seconds=0)
        # TTL=0 means already expired
        time.sleep(0.01)
        assert store.validate_and_consume(token) is None

    def test_multiple_tokens(self):
        store = EphemeralTokenStore()
        t1 = store.create("session-1")
        t2 = store.create("session-2")
        assert t1 != t2
        assert store.validate_and_consume(t1) == "session-1"
        assert store.validate_and_consume(t2) == "session-2"

    def test_cleanup_expired(self):
        store = EphemeralTokenStore()
        store.create("old", ttl_seconds=0)
        store.create("new", ttl_seconds=300)
        time.sleep(0.01)
        store.cleanup_expired()
        assert len(store._tokens) == 1
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_sandbox/test_token_store.py -v`
Expected: FAIL — module not found

**Step 3: Implement**

Create `src/everstaff/sandbox/ipc/channel.py`:

```python
"""Abstract IPC channel for sandbox communication."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable, Awaitable


class IpcChannel(ABC):
    """Abstract bidirectional IPC channel.

    Client side connects to server; supports request/response and
    fire-and-forget notifications. Server can push messages to client.
    """

    @abstractmethod
    async def connect(self, address: str) -> None:
        """Connect to the IPC server."""

    @abstractmethod
    async def send_request(self, method: str, params: dict[str, Any]) -> Any:
        """Send request and wait for response. Returns result dict."""

    @abstractmethod
    async def send_notification(self, method: str, params: dict[str, Any]) -> None:
        """Fire-and-forget notification (no response expected)."""

    @abstractmethod
    def on_push(self, method: str, handler: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
        """Register handler for server-pushed messages."""

    @abstractmethod
    async def close(self) -> None:
        """Close the connection."""

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Whether the channel is connected."""
```

Create `src/everstaff/sandbox/token_store.py`:

```python
"""Ephemeral token store for sandbox authentication."""
from __future__ import annotations

import secrets
import time


class _TokenEntry:
    __slots__ = ("session_id", "created_at", "ttl_seconds", "consumed")

    def __init__(self, session_id: str, ttl_seconds: float) -> None:
        self.session_id = session_id
        self.created_at = time.monotonic()
        self.ttl_seconds = ttl_seconds
        self.consumed = False

    def is_valid(self) -> bool:
        if self.consumed:
            return False
        return (time.monotonic() - self.created_at) < self.ttl_seconds


class EphemeralTokenStore:
    """Manages single-use, TTL-based tokens for sandbox authentication."""

    def __init__(self) -> None:
        self._tokens: dict[str, _TokenEntry] = {}

    def create(self, session_id: str, ttl_seconds: float = 30.0) -> str:
        """Create a new ephemeral token for the given session."""
        token = secrets.token_urlsafe(32)
        self._tokens[token] = _TokenEntry(session_id, ttl_seconds)
        return token

    def validate_and_consume(self, token: str) -> str | None:
        """Validate token and consume it. Returns session_id if valid, None otherwise."""
        entry = self._tokens.get(token)
        if entry is None or not entry.is_valid():
            return None
        entry.consumed = True
        return entry.session_id

    def cleanup_expired(self) -> None:
        """Remove expired or consumed tokens."""
        self._tokens = {
            t: e for t, e in self._tokens.items()
            if not e.consumed and e.is_valid()
        }
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_sandbox/test_token_store.py -v`
Expected: All 6 tests PASS

**Step 5: Commit**

```bash
git add src/everstaff/sandbox/ipc/channel.py src/everstaff/sandbox/token_store.py tests/test_sandbox/test_token_store.py
git commit -m "feat: add IpcChannel ABC and EphemeralTokenStore"
```

---

## Task 3: UnixSocketChannel Implementation

**Files:**
- Create: `src/everstaff/sandbox/ipc/unix_socket.py`
- Create: `tests/test_sandbox/test_ipc/test_unix_socket.py`

**Step 1: Write the failing tests**

Create `tests/test_sandbox/test_ipc/test_unix_socket.py`:

```python
"""Tests for UnixSocketChannel — client/server integration."""
import asyncio
import json
import pytest
import tempfile
from pathlib import Path

from everstaff.sandbox.ipc.unix_socket import UnixSocketChannel, UnixSocketServer


@pytest.mark.asyncio
class TestUnixSocketChannel:
    async def test_connect_and_request(self, tmp_path):
        socket_path = str(tmp_path / "test.sock")

        # Simple echo server
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

    async def test_notification_no_response(self, tmp_path):
        socket_path = str(tmp_path / "test.sock")
        received = []

        async def handler(method, params, send_response):
            received.append((method, params))
            # Notifications have no id — handler should not send response

        server = UnixSocketServer(socket_path, handler)
        await server.start()
        try:
            client = UnixSocketChannel()
            await client.connect(socket_path)
            try:
                await client.send_notification("tracer.event", {"kind": "test"})
                await asyncio.sleep(0.05)  # let server process
                assert len(received) == 1
                assert received[0] == ("tracer.event", {"kind": "test"})
            finally:
                await client.close()
        finally:
            await server.stop()

    async def test_server_push(self, tmp_path):
        socket_path = str(tmp_path / "test.sock")
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

            try:
                # Server pushes a message to client
                await server.push_to_all("cancel", {"session_id": "s1"})
                await asyncio.wait_for(push_received.wait(), timeout=2.0)
                assert push_data == {"session_id": "s1"}
            finally:
                await client.close()
        finally:
            await server.stop()

    async def test_multiple_concurrent_requests(self, tmp_path):
        socket_path = str(tmp_path / "test.sock")

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

    async def test_is_connected(self, tmp_path):
        socket_path = str(tmp_path / "test.sock")

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
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_sandbox/test_ipc/test_unix_socket.py -v`
Expected: FAIL — module not found

**Step 3: Implement**

Create `src/everstaff/sandbox/ipc/unix_socket.py`:

```python
"""Unix socket IPC channel and server."""
from __future__ import annotations

import asyncio
import json
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
            self._clients.remove(writer)
            writer.close()
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_sandbox/test_ipc/test_unix_socket.py -v`
Expected: All 5 tests PASS

**Step 5: Commit**

```bash
git add src/everstaff/sandbox/ipc/unix_socket.py tests/test_sandbox/test_ipc/test_unix_socket.py
git commit -m "feat: add UnixSocketChannel and UnixSocketServer"
```

---

## Task 4: ProxyMemoryStore

**Files:**
- Create: `src/everstaff/sandbox/proxy/__init__.py`
- Create: `src/everstaff/sandbox/proxy/memory_store.py`
- Create: `tests/test_sandbox/test_proxy/__init__.py`
- Create: `tests/test_sandbox/test_proxy/test_memory_store.py`

**Step 1: Write the failing tests**

Create `tests/test_sandbox/test_proxy/__init__.py` (empty).

Create `tests/test_sandbox/test_proxy/test_memory_store.py`:

```python
"""Tests for ProxyMemoryStore."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from everstaff.protocols import Message
from everstaff.sandbox.proxy.memory_store import ProxyMemoryStore


def _make_mock_channel():
    """Create a mock IpcChannel for testing."""
    channel = MagicMock()
    channel.send_request = AsyncMock()
    channel.send_notification = AsyncMock()
    return channel


@pytest.mark.asyncio
class TestProxyMemoryStore:
    async def test_save_sends_request(self):
        channel = _make_mock_channel()
        channel.send_request.return_value = None
        store = ProxyMemoryStore(channel)
        msgs = [Message(role="user", content="hello")]
        await store.save("s1", msgs, agent_name="test-agent", status="running")
        channel.send_request.assert_called_once()
        call_args = channel.send_request.call_args
        assert call_args[0][0] == "memory.save"
        params = call_args[0][1]
        assert params["session_id"] == "s1"
        assert params["agent_name"] == "test-agent"
        assert params["status"] == "running"
        assert len(params["messages"]) == 1

    async def test_load_returns_messages(self):
        channel = _make_mock_channel()
        channel.send_request.return_value = {
            "messages": [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "hello"},
            ]
        }
        store = ProxyMemoryStore(channel)
        msgs = await store.load("s1")
        assert len(msgs) == 2
        assert msgs[0].role == "user"
        assert msgs[1].content == "hello"

    async def test_load_empty(self):
        channel = _make_mock_channel()
        channel.send_request.return_value = {"messages": []}
        store = ProxyMemoryStore(channel)
        msgs = await store.load("s1")
        assert msgs == []

    async def test_save_workflow(self):
        channel = _make_mock_channel()
        channel.send_request.return_value = None
        store = ProxyMemoryStore(channel)
        await store.save_workflow("s1", {"type": "test"})
        channel.send_request.assert_called_once()
        assert channel.send_request.call_args[0][0] == "memory.save_workflow"

    async def test_load_workflows(self):
        channel = _make_mock_channel()
        channel.send_request.return_value = {"workflows": [{"type": "test"}]}
        store = ProxyMemoryStore(channel)
        result = await store.load_workflows("s1")
        assert len(result) == 1
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_sandbox/test_proxy/test_memory_store.py -v`
Expected: FAIL — module not found

**Step 3: Implement**

Create `src/everstaff/sandbox/proxy/__init__.py`:
```python
"""Proxy adapters for sandbox-to-orchestrator communication."""
```

Create `src/everstaff/sandbox/proxy/memory_store.py`:

```python
"""ProxyMemoryStore — forwards MemoryStore calls over IPC channel."""
from __future__ import annotations

from typing import Any, TYPE_CHECKING

from everstaff.protocols import Message, Episode, WorkingState

if TYPE_CHECKING:
    from everstaff.sandbox.ipc.channel import IpcChannel


class ProxyMemoryStore:
    """MemoryStore that forwards all operations over IPC to orchestrator."""

    def __init__(self, channel: "IpcChannel") -> None:
        self._channel = channel

    async def load(self, session_id: str) -> list[Message]:
        result = await self._channel.send_request("memory.load", {
            "session_id": session_id,
        })
        return [
            Message(
                role=m.get("role", "user"),
                content=m.get("content"),
                tool_calls=m.get("tool_calls"),
                tool_call_id=m.get("tool_call_id"),
                name=m.get("name"),
                thinking=m.get("thinking"),
            )
            for m in result.get("messages", [])
        ]

    async def save(
        self,
        session_id: str,
        messages: list[Message],
        *,
        agent_name: str | None = None,
        agent_uuid: str | None = None,
        parent_session_id: str | None = None,
        stats: Any | None = None,
        status: str | None = None,
        system_prompt: str | None = None,
        title: str | None = None,
        max_tokens: int | None = None,
        initiated_by: str | None = None,
        trigger: Any | None = None,
        hitl_requests: list[dict] | None = None,
        extra_permissions: list[str] | None = None,
    ) -> None:
        params: dict[str, Any] = {
            "session_id": session_id,
            "messages": [m.to_dict() for m in messages],
        }
        # Only include non-None kwargs to keep payload small
        for key, val in [
            ("agent_name", agent_name), ("agent_uuid", agent_uuid),
            ("parent_session_id", parent_session_id),
            ("status", status), ("system_prompt", system_prompt),
            ("title", title), ("max_tokens", max_tokens),
            ("initiated_by", initiated_by),
            ("hitl_requests", hitl_requests),
            ("extra_permissions", extra_permissions),
        ]:
            if val is not None:
                params[key] = val
        if stats is not None:
            import dataclasses
            params["stats"] = dataclasses.asdict(stats) if dataclasses.is_dataclass(stats) else stats
        if trigger is not None:
            import dataclasses
            params["trigger"] = dataclasses.asdict(trigger) if dataclasses.is_dataclass(trigger) else trigger
        await self._channel.send_request("memory.save", params)

    async def load_stats(self, session_id: str) -> Any:
        result = await self._channel.send_request("memory.load_stats", {
            "session_id": session_id,
        })
        return result.get("stats")

    async def save_workflow(self, session_id: str, record: Any) -> None:
        await self._channel.send_request("memory.save_workflow", {
            "session_id": session_id,
            "record": record,
        })

    async def load_workflows(self, session_id: str) -> list:
        result = await self._channel.send_request("memory.load_workflows", {
            "session_id": session_id,
        })
        return result.get("workflows", [])

    # L1: working memory
    async def working_load(self, agent_id: str) -> WorkingState:
        result = await self._channel.send_request("memory.working_load", {"agent_id": agent_id})
        return WorkingState(**result)

    async def working_save(self, agent_id: str, state: WorkingState) -> None:
        import dataclasses
        await self._channel.send_request("memory.working_save", {
            "agent_id": agent_id,
            "state": dataclasses.asdict(state),
        })

    # L2: episodic memory
    async def episode_append(self, agent_id: str, episode: Episode) -> None:
        import dataclasses
        await self._channel.send_request("memory.episode_append", {
            "agent_id": agent_id,
            "episode": dataclasses.asdict(episode),
        })

    async def episode_query(self, agent_id: str, days: int = 1, tags: list[str] | None = None, limit: int = 50) -> list[Episode]:
        result = await self._channel.send_request("memory.episode_query", {
            "agent_id": agent_id, "days": days, "tags": tags or [], "limit": limit,
        })
        return [Episode(**e) for e in result.get("episodes", [])]

    # L3: semantic memory
    async def semantic_read(self, agent_id: str, topic: str = "index") -> str:
        result = await self._channel.send_request("memory.semantic_read", {
            "agent_id": agent_id, "topic": topic,
        })
        return result.get("content", "")

    async def semantic_write(self, agent_id: str, topic: str, content: str) -> None:
        await self._channel.send_request("memory.semantic_write", {
            "agent_id": agent_id, "topic": topic, "content": content,
        })

    async def semantic_list(self, agent_id: str) -> list[str]:
        result = await self._channel.send_request("memory.semantic_list", {
            "agent_id": agent_id,
        })
        return result.get("topics", [])
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_sandbox/test_proxy/test_memory_store.py -v`
Expected: All 5 tests PASS

**Step 5: Commit**

```bash
git add src/everstaff/sandbox/proxy/ tests/test_sandbox/test_proxy/
git commit -m "feat: add ProxyMemoryStore for sandbox IPC"
```

---

## Task 5: ProxyTracer + ProxyFileStore

**Files:**
- Create: `src/everstaff/sandbox/proxy/tracer.py`
- Create: `src/everstaff/sandbox/proxy/file_store.py`
- Create: `tests/test_sandbox/test_proxy/test_tracer.py`
- Create: `tests/test_sandbox/test_proxy/test_file_store.py`

**Step 1: Write the failing tests**

Create `tests/test_sandbox/test_proxy/test_tracer.py`:

```python
"""Tests for ProxyTracer."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from everstaff.protocols import TraceEvent
from everstaff.sandbox.proxy.tracer import ProxyTracer


@pytest.mark.asyncio
class TestProxyTracer:
    async def test_on_event_sends_notification(self):
        channel = MagicMock()
        channel.send_notification = AsyncMock()
        tracer = ProxyTracer(channel)

        event = TraceEvent(kind="session_start", session_id="s1", data={"agent_name": "test"})
        tracer.on_event(event)

        # Give the background task time to execute
        await asyncio.sleep(0.05)

        channel.send_notification.assert_called_once()
        call_args = channel.send_notification.call_args
        assert call_args[0][0] == "tracer.event"
        params = call_args[0][1]
        assert params["kind"] == "session_start"
        assert params["session_id"] == "s1"

    async def test_aflush_is_noop(self):
        channel = MagicMock()
        channel.send_notification = AsyncMock()
        tracer = ProxyTracer(channel)
        # Should not raise
        await tracer.aflush()
```

Create `tests/test_sandbox/test_proxy/test_file_store.py`:

```python
"""Tests for ProxyFileStore."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from everstaff.sandbox.proxy.file_store import ProxyFileStore


def _make_mock_channel():
    channel = MagicMock()
    channel.send_request = AsyncMock()
    return channel


@pytest.mark.asyncio
class TestProxyFileStore:
    async def test_read(self):
        channel = _make_mock_channel()
        channel.send_request.return_value = {"data": "aGVsbG8="}  # base64 "hello"
        store = ProxyFileStore(channel)
        data = await store.read("session/file.txt")
        channel.send_request.assert_called_once_with("file.read", {"path": "session/file.txt"})

    async def test_write(self):
        channel = _make_mock_channel()
        channel.send_request.return_value = None
        store = ProxyFileStore(channel)
        await store.write("session/file.txt", b"hello")
        channel.send_request.assert_called_once()
        params = channel.send_request.call_args[0][1]
        assert params["path"] == "session/file.txt"

    async def test_exists(self):
        channel = _make_mock_channel()
        channel.send_request.return_value = {"exists": True}
        store = ProxyFileStore(channel)
        result = await store.exists("session/cancel.signal")
        assert result is True

    async def test_delete(self):
        channel = _make_mock_channel()
        channel.send_request.return_value = None
        store = ProxyFileStore(channel)
        await store.delete("session/cancel.signal")
        channel.send_request.assert_called_once_with("file.delete", {"path": "session/cancel.signal"})

    async def test_list(self):
        channel = _make_mock_channel()
        channel.send_request.return_value = {"files": ["a.txt", "b.txt"]}
        store = ProxyFileStore(channel)
        result = await store.list("session/")
        assert result == ["a.txt", "b.txt"]
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_sandbox/test_proxy/test_tracer.py tests/test_sandbox/test_proxy/test_file_store.py -v`
Expected: FAIL — module not found

**Step 3: Implement**

Create `src/everstaff/sandbox/proxy/tracer.py`:

```python
"""ProxyTracer — forwards trace events over IPC as fire-and-forget notifications."""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from everstaff.protocols import TraceEvent

if TYPE_CHECKING:
    from everstaff.sandbox.ipc.channel import IpcChannel

logger = logging.getLogger(__name__)


class ProxyTracer:
    """TracingBackend that forwards all events over IPC to orchestrator.

    Uses fire-and-forget notifications for low latency.
    """

    def __init__(self, channel: "IpcChannel") -> None:
        self._channel = channel

    def on_event(self, event: TraceEvent) -> None:
        """Forward trace event as IPC notification (non-blocking)."""
        params = {
            "kind": event.kind,
            "session_id": event.session_id,
            "parent_session_id": event.parent_session_id,
            "timestamp": event.timestamp,
            "duration_ms": event.duration_ms,
            "data": event.data,
            "trace_id": event.trace_id,
            "span_id": event.span_id,
            "parent_span_id": event.parent_span_id,
        }
        asyncio.create_task(self._send(params))

    async def _send(self, params: dict) -> None:
        try:
            await self._channel.send_notification("tracer.event", params)
        except Exception:
            logger.debug("Failed to send trace event via IPC", exc_info=True)

    async def aflush(self) -> None:
        """No-op: notifications are fire-and-forget."""
        pass
```

Create `src/everstaff/sandbox/proxy/file_store.py`:

```python
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
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_sandbox/test_proxy/ -v`
Expected: All proxy tests PASS (memory_store + tracer + file_store)

**Step 5: Commit**

```bash
git add src/everstaff/sandbox/proxy/tracer.py src/everstaff/sandbox/proxy/file_store.py tests/test_sandbox/test_proxy/test_tracer.py tests/test_sandbox/test_proxy/test_file_store.py
git commit -m "feat: add ProxyTracer and ProxyFileStore for sandbox IPC"
```

---

## Task 6: SandboxEnvironment

**Files:**
- Create: `src/everstaff/sandbox/environment.py`
- Create: `tests/test_sandbox/test_environment.py`

**Step 1: Write the failing tests**

Create `tests/test_sandbox/test_environment.py`:

```python
"""Tests for SandboxEnvironment."""
import pytest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

from everstaff.core.secret_store import SecretStore
from everstaff.sandbox.environment import SandboxEnvironment
from everstaff.sandbox.proxy.memory_store import ProxyMemoryStore
from everstaff.sandbox.proxy.tracer import ProxyTracer
from everstaff.sandbox.proxy.file_store import ProxyFileStore


class TestSandboxEnvironment:
    def test_build_memory_store_returns_proxy(self, tmp_path):
        channel = MagicMock()
        secret_store = SecretStore({"KEY": "val"})
        env = SandboxEnvironment(
            channel=channel,
            secret_store=secret_store,
            workspace_dir=tmp_path,
        )
        store = env.build_memory_store()
        assert isinstance(store, ProxyMemoryStore)

    def test_build_tracer_returns_proxy(self, tmp_path):
        channel = MagicMock()
        secret_store = SecretStore()
        env = SandboxEnvironment(
            channel=channel,
            secret_store=secret_store,
            workspace_dir=tmp_path,
        )
        tracer = env.build_tracer(session_id="s1")
        assert isinstance(tracer, ProxyTracer)

    def test_build_file_store_returns_proxy(self, tmp_path):
        channel = MagicMock()
        secret_store = SecretStore()
        env = SandboxEnvironment(
            channel=channel,
            secret_store=secret_store,
            workspace_dir=tmp_path,
        )
        store = env.build_file_store()
        assert isinstance(store, ProxyFileStore)

    def test_working_dir_returns_workspace(self, tmp_path):
        channel = MagicMock()
        secret_store = SecretStore()
        env = SandboxEnvironment(
            channel=channel,
            secret_store=secret_store,
            workspace_dir=tmp_path,
        )
        assert env.working_dir("any-session") == tmp_path

    def test_secret_store_property(self, tmp_path):
        channel = MagicMock()
        secret_store = SecretStore({"API_KEY": "secret123"})
        env = SandboxEnvironment(
            channel=channel,
            secret_store=secret_store,
            workspace_dir=tmp_path,
        )
        assert env.secret_store.get("API_KEY") == "secret123"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_sandbox/test_environment.py -v`
Expected: FAIL — module not found

**Step 3: Implement**

Create `src/everstaff/sandbox/environment.py`:

```python
"""SandboxEnvironment — RuntimeEnvironment for sandbox processes."""
from __future__ import annotations

from pathlib import Path
from typing import Any, TYPE_CHECKING

from everstaff.builder.environment import RuntimeEnvironment
from everstaff.sandbox.proxy.memory_store import ProxyMemoryStore
from everstaff.sandbox.proxy.tracer import ProxyTracer
from everstaff.sandbox.proxy.file_store import ProxyFileStore

if TYPE_CHECKING:
    from everstaff.core.config import FrameworkConfig
    from everstaff.core.secret_store import SecretStore
    from everstaff.protocols import FileStore, LLMClient, MemoryStore, TracingBackend
    from everstaff.sandbox.ipc.channel import IpcChannel


class SandboxEnvironment(RuntimeEnvironment):
    """RuntimeEnvironment for sandbox processes.

    All infrastructure (memory, tracer, file store) is proxied over IPC
    to the orchestrator. LLM calls execute directly in sandbox.
    """

    def __init__(
        self,
        channel: "IpcChannel",
        secret_store: "SecretStore",
        workspace_dir: Path,
        config: "FrameworkConfig | None" = None,
    ) -> None:
        super().__init__(config=config)
        self._channel = channel
        self._secret_store = secret_store
        self._workspace_dir = workspace_dir

    def build_memory_store(self, max_tokens: int | None = None) -> "MemoryStore":
        return ProxyMemoryStore(self._channel)

    def build_tracer(self, session_id: str = "") -> "TracingBackend":
        return ProxyTracer(self._channel)

    def build_file_store(self) -> "FileStore":
        return ProxyFileStore(self._channel)

    def build_llm_client(self, model: str, **kwargs: Any) -> "LLMClient":
        from everstaff.llm.litellm_client import LiteLLMClient
        return LiteLLMClient(model=model, **kwargs)

    def working_dir(self, session_id: str) -> Path:
        self._workspace_dir.mkdir(parents=True, exist_ok=True)
        return self._workspace_dir

    @property
    def secret_store(self) -> "SecretStore":
        return self._secret_store
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_sandbox/test_environment.py -v`
Expected: All 5 tests PASS

**Step 5: Commit**

```bash
git add src/everstaff/sandbox/environment.py tests/test_sandbox/test_environment.py
git commit -m "feat: add SandboxEnvironment with proxy adapters"
```

---

## Task 7: IPC Server Handler

**Files:**
- Create: `src/everstaff/sandbox/ipc/server_handler.py`
- Create: `tests/test_sandbox/test_ipc/test_server_handler.py`

**Step 1: Write the failing tests**

Create `tests/test_sandbox/test_ipc/test_server_handler.py`:

```python
"""Tests for IPC server handler that routes messages to real implementations."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from everstaff.protocols import Message, TraceEvent
from everstaff.sandbox.ipc.server_handler import IpcServerHandler
from everstaff.sandbox.token_store import EphemeralTokenStore
from everstaff.core.secret_store import SecretStore


def _make_handler():
    memory = MagicMock()
    memory.save = AsyncMock()
    memory.load = AsyncMock(return_value=[Message(role="user", content="hi")])
    memory.load_stats = AsyncMock(return_value=None)
    memory.save_workflow = AsyncMock()
    memory.load_workflows = AsyncMock(return_value=[])

    tracer = MagicMock()
    tracer.on_event = MagicMock()

    file_store = MagicMock()
    file_store.read = AsyncMock(return_value=b"data")
    file_store.write = AsyncMock()
    file_store.exists = AsyncMock(return_value=True)
    file_store.delete = AsyncMock()
    file_store.list = AsyncMock(return_value=["a.txt"])

    token_store = EphemeralTokenStore()
    secret_store = SecretStore({"API_KEY": "secret"})

    handler = IpcServerHandler(
        memory_store=memory,
        tracer=tracer,
        file_store=file_store,
        token_store=token_store,
        secret_store=secret_store,
    )
    return handler, memory, tracer, file_store, token_store


@pytest.mark.asyncio
class TestIpcServerHandler:
    async def test_auth_success(self):
        handler, _, _, _, token_store = _make_handler()
        token = token_store.create("session-1")
        result = await handler.handle("auth", {"token": token})
        assert "secrets" in result
        assert result["secrets"]["API_KEY"] == "secret"

    async def test_auth_invalid_token(self):
        handler, _, _, _, _ = _make_handler()
        result = await handler.handle("auth", {"token": "invalid"})
        assert "error" in result

    async def test_memory_save(self):
        handler, memory, _, _, _ = _make_handler()
        result = await handler.handle("memory.save", {
            "session_id": "s1",
            "messages": [{"role": "user", "content": "hello"}],
            "status": "running",
        })
        memory.save.assert_called_once()

    async def test_memory_load(self):
        handler, memory, _, _, _ = _make_handler()
        result = await handler.handle("memory.load", {"session_id": "s1"})
        assert "messages" in result
        assert len(result["messages"]) == 1

    async def test_tracer_event(self):
        handler, _, tracer, _, _ = _make_handler()
        result = await handler.handle("tracer.event", {
            "kind": "session_start",
            "session_id": "s1",
            "data": {},
            "timestamp": "2026-01-01T00:00:00Z",
        })
        tracer.on_event.assert_called_once()

    async def test_file_exists(self):
        handler, _, _, file_store, _ = _make_handler()
        result = await handler.handle("file.exists", {"path": "s1/cancel.signal"})
        assert result["exists"] is True

    async def test_file_read(self):
        handler, _, _, file_store, _ = _make_handler()
        result = await handler.handle("file.read", {"path": "s1/file.txt"})
        assert "data" in result

    async def test_unknown_method(self):
        handler, _, _, _, _ = _make_handler()
        result = await handler.handle("unknown.method", {})
        assert "error" in result
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_sandbox/test_ipc/test_server_handler.py -v`
Expected: FAIL — module not found

**Step 3: Implement**

Create `src/everstaff/sandbox/ipc/server_handler.py`:

```python
"""IPC server handler — routes sandbox messages to real implementations."""
from __future__ import annotations

import base64
import logging
from typing import Any, TYPE_CHECKING

from everstaff.protocols import Message, TraceEvent

if TYPE_CHECKING:
    from everstaff.protocols import FileStore, MemoryStore, TracingBackend
    from everstaff.sandbox.token_store import EphemeralTokenStore
    from everstaff.core.secret_store import SecretStore

logger = logging.getLogger(__name__)


class IpcServerHandler:
    """Routes IPC messages from sandbox to real orchestrator implementations."""

    def __init__(
        self,
        memory_store: "MemoryStore",
        tracer: "TracingBackend",
        file_store: "FileStore",
        token_store: "EphemeralTokenStore",
        secret_store: "SecretStore",
        channel_manager: Any = None,
    ) -> None:
        self._memory = memory_store
        self._tracer = tracer
        self._file_store = file_store
        self._token_store = token_store
        self._secret_store = secret_store
        self._channel_manager = channel_manager

    async def handle(self, method: str, params: dict[str, Any]) -> Any:
        """Route a single IPC message to the appropriate handler."""
        try:
            if method == "auth":
                return self._handle_auth(params)
            elif method == "memory.save":
                return await self._handle_memory_save(params)
            elif method == "memory.load":
                return await self._handle_memory_load(params)
            elif method == "memory.load_stats":
                return await self._handle_memory_load_stats(params)
            elif method == "memory.save_workflow":
                return await self._handle_memory_save_workflow(params)
            elif method == "memory.load_workflows":
                return await self._handle_memory_load_workflows(params)
            elif method == "tracer.event":
                return self._handle_tracer_event(params)
            elif method.startswith("file."):
                return await self._handle_file_op(method, params)
            elif method.startswith("memory."):
                return await self._handle_memory_extended(method, params)
            else:
                return {"error": f"Unknown method: {method}"}
        except Exception as e:
            logger.exception("IPC handler error for method '%s'", method)
            return {"error": str(e)}

    def _handle_auth(self, params: dict[str, Any]) -> dict[str, Any]:
        token = params.get("token", "")
        session_id = self._token_store.validate_and_consume(token)
        if session_id is None:
            return {"error": "Invalid or expired token"}
        return {"session_id": session_id, "secrets": self._secret_store.as_dict()}

    async def _handle_memory_save(self, params: dict[str, Any]) -> dict[str, Any]:
        session_id = params.pop("session_id")
        raw_messages = params.pop("messages", [])
        messages = [
            Message(
                role=m.get("role", "user"),
                content=m.get("content"),
                tool_calls=m.get("tool_calls"),
                tool_call_id=m.get("tool_call_id"),
                name=m.get("name"),
                thinking=m.get("thinking"),
            )
            for m in raw_messages
        ]
        # Reconstruct stats if provided
        stats = params.pop("stats", None)
        if stats and isinstance(stats, dict):
            from everstaff.schema.token_stats import SessionStats
            stats = SessionStats(**stats)
        trigger = params.pop("trigger", None)
        if trigger and isinstance(trigger, dict):
            from everstaff.protocols import AgentEvent
            trigger = AgentEvent(**trigger)
        await self._memory.save(session_id, messages, stats=stats, trigger=trigger, **params)
        return {}

    async def _handle_memory_load(self, params: dict[str, Any]) -> dict[str, Any]:
        messages = await self._memory.load(params["session_id"])
        return {"messages": [m.to_dict() for m in messages]}

    async def _handle_memory_load_stats(self, params: dict[str, Any]) -> dict[str, Any]:
        load_stats_fn = getattr(self._memory, "load_stats", None)
        if load_stats_fn:
            stats = await load_stats_fn(params["session_id"])
            if stats:
                import dataclasses
                return {"stats": dataclasses.asdict(stats) if dataclasses.is_dataclass(stats) else stats}
        return {"stats": None}

    async def _handle_memory_save_workflow(self, params: dict[str, Any]) -> dict[str, Any]:
        await self._memory.save_workflow(params["session_id"], params.get("record"))
        return {}

    async def _handle_memory_load_workflows(self, params: dict[str, Any]) -> dict[str, Any]:
        workflows = await self._memory.load_workflows(params["session_id"])
        return {"workflows": workflows}

    def _handle_tracer_event(self, params: dict[str, Any]) -> dict[str, Any]:
        event = TraceEvent(
            kind=params.get("kind", ""),
            session_id=params.get("session_id", ""),
            parent_session_id=params.get("parent_session_id"),
            timestamp=params.get("timestamp", ""),
            duration_ms=params.get("duration_ms"),
            data=params.get("data", {}),
            trace_id=params.get("trace_id", ""),
            span_id=params.get("span_id", ""),
            parent_span_id=params.get("parent_span_id"),
        )
        self._tracer.on_event(event)
        return {}

    async def _handle_file_op(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        op = method.split(".", 1)[1]
        path = params.get("path", "")
        if op == "read":
            data = await self._file_store.read(path)
            return {"data": base64.b64encode(data).decode()}
        elif op == "write":
            raw = base64.b64decode(params.get("data", ""))
            await self._file_store.write(path, raw)
            return {}
        elif op == "exists":
            return {"exists": await self._file_store.exists(path)}
        elif op == "delete":
            await self._file_store.delete(path)
            return {}
        elif op == "list":
            files = await self._file_store.list(params.get("prefix", ""))
            return {"files": files}
        return {"error": f"Unknown file operation: {op}"}

    async def _handle_memory_extended(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Handle L1/L2/L3 memory operations."""
        op = method.split(".", 1)[1]
        if op == "working_load":
            from everstaff.protocols import WorkingState
            state = await self._memory.working_load(params["agent_id"])
            import dataclasses
            return dataclasses.asdict(state)
        elif op == "working_save":
            from everstaff.protocols import WorkingState
            await self._memory.working_save(params["agent_id"], WorkingState(**params["state"]))
            return {}
        elif op == "episode_append":
            from everstaff.protocols import Episode
            await self._memory.episode_append(params["agent_id"], Episode(**params["episode"]))
            return {}
        elif op == "episode_query":
            episodes = await self._memory.episode_query(
                params["agent_id"], params.get("days", 1), params.get("tags"), params.get("limit", 50)
            )
            import dataclasses
            return {"episodes": [dataclasses.asdict(e) for e in episodes]}
        elif op == "semantic_read":
            content = await self._memory.semantic_read(params["agent_id"], params.get("topic", "index"))
            return {"content": content}
        elif op == "semantic_write":
            await self._memory.semantic_write(params["agent_id"], params["topic"], params["content"])
            return {}
        elif op == "semantic_list":
            topics = await self._memory.semantic_list(params["agent_id"])
            return {"topics": topics}
        return {"error": f"Unknown memory operation: {op}"}
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_sandbox/test_ipc/test_server_handler.py -v`
Expected: All 8 tests PASS

**Step 5: Commit**

```bash
git add src/everstaff/sandbox/ipc/server_handler.py tests/test_sandbox/test_ipc/test_server_handler.py
git commit -m "feat: add IPC server handler for routing sandbox messages"
```

---

## Task 8: End-to-End Integration Test

**Files:**
- Create: `tests/test_sandbox/test_ipc/test_integration.py`

This task tests the full pipeline: client ↔ UnixSocket ↔ server handler ↔ real (mock) implementations.

**Step 1: Write the test**

Create `tests/test_sandbox/test_ipc/test_integration.py`:

```python
"""End-to-end integration test: sandbox proxy → IPC → server handler → mock impl."""
import asyncio
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from everstaff.core.secret_store import SecretStore
from everstaff.protocols import Message
from everstaff.sandbox.ipc.unix_socket import UnixSocketChannel, UnixSocketServer
from everstaff.sandbox.ipc.server_handler import IpcServerHandler
from everstaff.sandbox.proxy.memory_store import ProxyMemoryStore
from everstaff.sandbox.proxy.tracer import ProxyTracer
from everstaff.sandbox.proxy.file_store import ProxyFileStore
from everstaff.sandbox.token_store import EphemeralTokenStore


@pytest.mark.asyncio
class TestEndToEndIpc:
    async def _setup(self, tmp_path):
        """Set up server + client connected over unix socket."""
        socket_path = str(tmp_path / "ipc.sock")

        # Real-ish mock implementations
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

    async def test_auth_and_secret_delivery(self, tmp_path):
        server, client, handler, token_store, _, _ = await self._setup(tmp_path)
        try:
            token = token_store.create("session-1")
            result = await client.send_request("auth", {"token": token})
            assert result["secrets"]["LLM_API_KEY"] == "sk-123"
            assert result["secrets"]["DB_URL"] == "postgres://..."
        finally:
            await client.close()
            await server.stop()

    async def test_proxy_memory_save_and_load(self, tmp_path):
        server, client, _, token_store, memory, _ = await self._setup(tmp_path)
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

    async def test_proxy_tracer_event(self, tmp_path):
        server, client, _, _, _, tracer = await self._setup(tmp_path)
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

    async def test_proxy_file_exists(self, tmp_path):
        server, client, _, _, _, _ = await self._setup(tmp_path)
        try:
            proxy = ProxyFileStore(client)
            exists = await proxy.exists("s1/cancel.signal")
            assert exists is False  # mock returns False
        finally:
            await client.close()
            await server.stop()

    async def test_cancel_push(self, tmp_path):
        server, client, _, _, _, _ = await self._setup(tmp_path)
        cancelled = asyncio.Event()

        async def on_cancel(params):
            cancelled.set()

        client.on_push("cancel", on_cancel)

        try:
            await server.push_to_all("cancel", {"session_id": "s1"})
            await asyncio.wait_for(cancelled.wait(), timeout=2.0)
            assert cancelled.is_set()
        finally:
            await client.close()
            await server.stop()
```

**Step 2: Run test**

Run: `uv run pytest tests/test_sandbox/test_ipc/test_integration.py -v`
Expected: All 5 tests PASS

**Step 3: Commit**

```bash
git add tests/test_sandbox/test_ipc/test_integration.py
git commit -m "test: add end-to-end IPC integration tests"
```

---

## Task 9: Update ExecutorManager for Cancel Support

**Files:**
- Modify: `src/everstaff/sandbox/manager.py`
- Modify: `tests/test_sandbox/test_manager.py`

**Step 1: Write the failing test**

Add to `tests/test_sandbox/test_manager.py`:

```python
async def test_has_active(self):
    """has_active returns True for running sessions."""
    factory = lambda: DummyExecutor()
    store = SecretStore({"K": "V"})
    mgr = ExecutorManager(factory, store)
    assert not mgr.has_active("s1")
    await mgr.get_or_create("s1")
    assert mgr.has_active("s1")
    await mgr.destroy("s1")
    assert not mgr.has_active("s1")
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_sandbox/test_manager.py::TestExecutorManager::test_has_active -v`
Expected: FAIL — `has_active` not found

**Step 3: Implement**

Add to `src/everstaff/sandbox/manager.py`:

```python
def has_active(self, session_id: str) -> bool:
    """Check if a session has an active (alive) executor."""
    executor = self._executors.get(session_id)
    return executor is not None and executor.is_alive
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_sandbox/test_manager.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add src/everstaff/sandbox/manager.py tests/test_sandbox/test_manager.py
git commit -m "feat: add has_active() to ExecutorManager for cancel support"
```

---

## Task 10: Run All Tests

**Step 1: Run full sandbox test suite**

Run: `uv run pytest tests/test_sandbox/ -v`
Expected: All tests PASS

**Step 2: Run all project tests (sanity check)**

Run: `uv run pytest tests/test_core/ tests/test_sandbox/ tests/test_builtin_tools/ tests/test_mcp_client/ -v`
Expected: All tests PASS (except pre-existing API test failures unrelated to our changes)

**Step 3: Commit if any fixups needed**

---

## Task 11: Sandbox Entry Point

**Files:**
- Create: `src/everstaff/sandbox/entry.py`
- Create: `tests/test_sandbox/test_entry.py`

**Step 1: Write the failing tests**

Create `tests/test_sandbox/test_entry.py`:

```python
"""Tests for sandbox entry point."""
import asyncio
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from everstaff.sandbox.entry import sandbox_main, parse_args


class TestParseArgs:
    def test_parse_args_basic(self):
        args = parse_args(["--socket-path", "/tmp/test.sock", "--token", "abc123",
                           "--session-id", "s1", "--agent-spec", '{"name":"test"}'])
        assert args.socket_path == "/tmp/test.sock"
        assert args.token == "abc123"
        assert args.session_id == "s1"
        assert args.agent_spec == '{"name":"test"}'

    def test_parse_args_with_workspace(self):
        args = parse_args(["--socket-path", "/tmp/test.sock", "--token", "abc",
                           "--session-id", "s1", "--agent-spec", "{}",
                           "--workspace-dir", "/work"])
        assert args.workspace_dir == "/work"


@pytest.mark.asyncio
class TestSandboxMain:
    async def test_connects_and_authenticates(self, tmp_path):
        """sandbox_main should connect to IPC, authenticate, get secrets."""
        mock_channel = MagicMock()
        mock_channel.connect = AsyncMock()
        mock_channel.send_request = AsyncMock(return_value={
            "secrets": {"API_KEY": "secret123"},
        })
        mock_channel.on_push = MagicMock()
        mock_channel.close = AsyncMock()

        with patch("everstaff.sandbox.entry.UnixSocketChannel", return_value=mock_channel), \
             patch("everstaff.sandbox.entry._run_agent", new_callable=AsyncMock) as mock_run:
            await sandbox_main(
                socket_path=str(tmp_path / "test.sock"),
                token="test-token",
                session_id="s1",
                agent_spec_json='{"name":"test"}',
                workspace_dir=str(tmp_path),
            )

        mock_channel.connect.assert_awaited_once_with(str(tmp_path / "test.sock"))
        mock_channel.send_request.assert_awaited_once_with("auth", {"token": "test-token"})
        mock_run.assert_awaited_once()

    async def test_registers_cancel_handler(self, tmp_path):
        """sandbox_main should register a cancel push handler."""
        mock_channel = MagicMock()
        mock_channel.connect = AsyncMock()
        mock_channel.send_request = AsyncMock(return_value={"secrets": {}})
        mock_channel.on_push = MagicMock()
        mock_channel.close = AsyncMock()

        with patch("everstaff.sandbox.entry.UnixSocketChannel", return_value=mock_channel), \
             patch("everstaff.sandbox.entry._run_agent", new_callable=AsyncMock):
            await sandbox_main(
                socket_path="/tmp/test.sock",
                token="t",
                session_id="s1",
                agent_spec_json='{"name":"test"}',
                workspace_dir=str(tmp_path),
            )

        # Verify cancel and hitl.resolution handlers were registered
        push_methods = [call.args[0] for call in mock_channel.on_push.call_args_list]
        assert "cancel" in push_methods
        assert "hitl.resolution" in push_methods

    async def test_closes_channel_on_exit(self, tmp_path):
        """Channel should be closed even if _run_agent raises."""
        mock_channel = MagicMock()
        mock_channel.connect = AsyncMock()
        mock_channel.send_request = AsyncMock(return_value={"secrets": {}})
        mock_channel.on_push = MagicMock()
        mock_channel.close = AsyncMock()

        with patch("everstaff.sandbox.entry.UnixSocketChannel", return_value=mock_channel), \
             patch("everstaff.sandbox.entry._run_agent", new_callable=AsyncMock,
                   side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError, match="boom"):
                await sandbox_main(
                    socket_path="/tmp/test.sock",
                    token="t",
                    session_id="s1",
                    agent_spec_json='{"name":"test"}',
                    workspace_dir=str(tmp_path),
                )

        mock_channel.close.assert_awaited_once()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_sandbox/test_entry.py -v`
Expected: FAIL — module `everstaff.sandbox.entry` not found

**Step 3: Implement**

Create `src/everstaff/sandbox/entry.py`:

```python
"""Sandbox process entry point.

This module is the main() for a sandbox subprocess. It:
1. Connects to orchestrator via IPC channel
2. Authenticates with ephemeral token and receives secrets
3. Builds SandboxEnvironment with proxy adapters
4. Runs AgentRuntime with the provided agent spec
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from everstaff.core.secret_store import SecretStore
from everstaff.sandbox.environment import SandboxEnvironment
from everstaff.sandbox.ipc.unix_socket import UnixSocketChannel

logger = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Everstaff sandbox process")
    parser.add_argument("--socket-path", required=True, help="IPC socket path")
    parser.add_argument("--token", required=True, help="Ephemeral auth token")
    parser.add_argument("--session-id", required=True, help="Session ID")
    parser.add_argument("--agent-spec", required=True, help="Agent spec JSON string")
    parser.add_argument("--workspace-dir", default="/work", help="Workspace directory")
    return parser.parse_args(argv)


async def sandbox_main(
    socket_path: str,
    token: str,
    session_id: str,
    agent_spec_json: str,
    workspace_dir: str,
) -> None:
    """Entry point for sandbox process."""
    # 1. Connect and authenticate
    channel = UnixSocketChannel()
    await channel.connect(socket_path)

    try:
        auth_result = await channel.send_request("auth", {"token": token})
        secret_store = SecretStore(auth_result.get("secrets", {}))

        # 2. Build environment
        workspace = Path(workspace_dir)
        workspace.mkdir(parents=True, exist_ok=True)
        env = SandboxEnvironment(
            channel=channel,
            secret_store=secret_store,
            workspace_dir=workspace,
        )

        # 3. Register cancel handler
        _cancelled = asyncio.Event()
        channel.on_push("cancel", lambda params: _cancelled.set())

        # 4. Register HITL resolution handler (placeholder — wired in Task 13)
        _hitl_resolutions: asyncio.Queue = asyncio.Queue()
        channel.on_push("hitl.resolution", lambda params: _hitl_resolutions.put_nowait(params))

        # 5. Run agent
        await _run_agent(
            env=env,
            session_id=session_id,
            agent_spec_json=agent_spec_json,
            cancelled=_cancelled,
            hitl_resolutions=_hitl_resolutions,
        )
    finally:
        await channel.close()


async def _run_agent(
    env: SandboxEnvironment,
    session_id: str,
    agent_spec_json: str,
    cancelled: asyncio.Event,
    hitl_resolutions: asyncio.Queue,
) -> None:
    """Build and run AgentRuntime. Separated for testability."""
    from everstaff.builder.agent_builder import AgentBuilder
    from everstaff.schema.agent_spec import AgentSpec

    spec = AgentSpec.model_validate_json(agent_spec_json)
    builder = AgentBuilder(spec, env, session_id=session_id)
    runtime, ctx = await builder.build()

    # Wire cancellation
    # TODO: connect _cancelled event to ctx.cancellation once CancellationToken is available

    async for _event in runtime.run_stream():
        pass  # All saves/traces go through proxies automatically


def main() -> None:
    """CLI entry point: python -m everstaff.sandbox.entry"""
    args = parse_args()
    asyncio.run(sandbox_main(
        socket_path=args.socket_path,
        token=args.token,
        session_id=args.session_id,
        agent_spec_json=args.agent_spec,
        workspace_dir=args.workspace_dir,
    ))


if __name__ == "__main__":
    main()
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_sandbox/test_entry.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add src/everstaff/sandbox/entry.py tests/test_sandbox/test_entry.py
git commit -m "feat: add sandbox process entry point (entry.py)"
```

---

## Task 12: ProcessSandbox IPC Integration

**Files:**
- Modify: `src/everstaff/sandbox/process_sandbox.py`
- Modify: `src/everstaff/sandbox/executor.py`
- Create: `tests/test_sandbox/test_process_sandbox_ipc.py`

This task upgrades ProcessSandbox from a simple subprocess runner to a full sandbox
that spawns a subprocess running `entry.py`, sets up the IPC server, handles auth,
and delivers secrets.

**Step 1: Write the failing tests**

Create `tests/test_sandbox/test_process_sandbox_ipc.py`:

```python
"""Tests for ProcessSandbox with IPC integration."""
import asyncio
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from everstaff.core.secret_store import SecretStore
from everstaff.sandbox.process_sandbox import ProcessSandbox
from everstaff.sandbox.ipc.token_store import EphemeralTokenStore


@pytest.mark.asyncio
class TestProcessSandboxIpc:
    async def test_start_creates_ipc_server(self, tmp_path):
        """start() should create and start an IPC server."""
        store = SecretStore({"API_KEY": "secret"})
        sandbox = ProcessSandbox(workdir=tmp_path, secret_store=store)
        await sandbox.start("test-session")
        try:
            assert sandbox.is_alive
            assert sandbox._ipc_socket_path is not None
            assert Path(sandbox._ipc_socket_path).parent.exists()
        finally:
            await sandbox.stop()

    async def test_stop_cleans_up_ipc(self, tmp_path):
        """stop() should close IPC server and remove socket file."""
        store = SecretStore()
        sandbox = ProcessSandbox(workdir=tmp_path, secret_store=store)
        await sandbox.start("test-session")
        socket_path = sandbox._ipc_socket_path
        await sandbox.stop()
        assert not sandbox.is_alive
        # Socket file should be cleaned up
        assert not Path(socket_path).exists()

    async def test_start_generates_ephemeral_token(self, tmp_path):
        """start() should generate an ephemeral token for sandbox auth."""
        store = SecretStore({"KEY": "val"})
        sandbox = ProcessSandbox(workdir=tmp_path, secret_store=store)
        await sandbox.start("test-session")
        try:
            assert sandbox._ephemeral_token is not None
            assert len(sandbox._ephemeral_token) > 0
        finally:
            await sandbox.stop()

    async def test_push_cancel(self, tmp_path):
        """push_cancel() should send cancel message to sandbox via IPC."""
        store = SecretStore()
        sandbox = ProcessSandbox(workdir=tmp_path, secret_store=store)
        await sandbox.start("test-session")
        try:
            # push_cancel should not raise even if no client connected
            await sandbox.push_cancel()
        finally:
            await sandbox.stop()

    async def test_push_hitl_resolution(self, tmp_path):
        """push_hitl_resolution() should send resolution to sandbox via IPC."""
        store = SecretStore()
        sandbox = ProcessSandbox(workdir=tmp_path, secret_store=store)
        await sandbox.start("test-session")
        try:
            await sandbox.push_hitl_resolution(
                hitl_id="h1", decision="approved", comment="ok"
            )
        finally:
            await sandbox.stop()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_sandbox/test_process_sandbox_ipc.py -v`
Expected: FAIL — `_ipc_socket_path` attribute not found

**Step 3: Update SandboxExecutor ABC**

In `src/everstaff/sandbox/executor.py`, add push methods:

```python
class SandboxExecutor(ABC):
    # ... existing methods ...

    async def push_cancel(self) -> None:
        """Push cancel signal to sandbox. Default: no-op for simple backends."""

    async def push_hitl_resolution(
        self, hitl_id: str, decision: str, comment: str = ""
    ) -> None:
        """Push HITL resolution to sandbox. Default: no-op for simple backends."""
```

**Step 4: Implement ProcessSandbox IPC integration**

Update `src/everstaff/sandbox/process_sandbox.py`:

```python
"""ProcessSandbox -- local subprocess-based sandbox backend with IPC."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING

from everstaff.sandbox.executor import SandboxExecutor
from everstaff.sandbox.ipc.server_handler import IpcServerHandler
from everstaff.sandbox.ipc.token_store import EphemeralTokenStore
from everstaff.sandbox.models import SandboxCommand, SandboxResult, SandboxStatus

if TYPE_CHECKING:
    from everstaff.core.secret_store import SecretStore

logger = logging.getLogger(__name__)


def _minimal_env() -> dict[str, str]:
    """Minimal environment for subprocess execution."""
    env: dict[str, str] = {}
    for key in ("PATH", "HOME", "USER", "LANG", "TERM"):
        val = os.environ.get(key)
        if val is not None:
            env[key] = val
    return env


class ProcessSandbox(SandboxExecutor):
    """Sandbox that runs agent in a local subprocess with IPC channel.

    Lifecycle:
    1. start() → creates IPC server + socket, generates ephemeral token
    2. Orchestrator spawns subprocess: python -m everstaff.sandbox.entry
    3. Subprocess connects, authenticates, receives secrets, runs AgentRuntime
    4. stop() → closes IPC server, terminates process, cleans up socket
    """

    def __init__(self, workdir: Path, secret_store: "SecretStore") -> None:
        self._workdir = workdir
        self._secret_store = secret_store
        self._session_id: str = ""
        self._alive: bool = False
        self._started_at: float = 0.0
        self._subprocess_env = _minimal_env()

        # IPC state
        self._ipc_socket_path: str | None = None
        self._ipc_server: asyncio.AbstractServer | None = None
        self._ipc_handler: IpcServerHandler | None = None
        self._ephemeral_token: str | None = None
        self._token_store: EphemeralTokenStore | None = None
        self._client_writer: asyncio.StreamWriter | None = None

    async def start(self, session_id: str) -> None:
        self._session_id = session_id
        self._workdir.mkdir(parents=True, exist_ok=True)

        # Create IPC socket in temp directory
        tmpdir = tempfile.mkdtemp(prefix="everstaff-ipc-")
        self._ipc_socket_path = os.path.join(tmpdir, f"{session_id}.sock")

        # Generate ephemeral token
        self._token_store = EphemeralTokenStore()
        self._ephemeral_token = self._token_store.create(session_id, ttl_seconds=30)

        # Start IPC server
        self._ipc_handler = IpcServerHandler(
            token_store=self._token_store,
            secret_store=self._secret_store,
        )
        self._ipc_server = await asyncio.start_unix_server(
            self._handle_connection,
            path=self._ipc_socket_path,
        )

        self._alive = True
        self._started_at = time.monotonic()
        logger.info("ProcessSandbox started for session %s at %s", session_id, self._workdir)

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Handle one sandbox subprocess IPC connection."""
        self._client_writer = writer
        try:
            async for line in reader:
                msg = json.loads(line)
                response = await self._ipc_handler.handle_message(msg)
                if response is not None:
                    writer.write(json.dumps(response).encode() + b"\n")
                    await writer.drain()
        except Exception as e:
            logger.debug("IPC connection closed: %s", e)
        finally:
            self._client_writer = None
            writer.close()

    async def execute(self, command: SandboxCommand) -> SandboxResult:
        if not self._alive:
            return SandboxResult(success=False, error="Sandbox not running")
        if command.type == "bash":
            return await self._exec_bash(command.payload)
        return SandboxResult(success=False, error=f"Unknown command type: {command.type}")

    async def stop(self) -> None:
        # Close IPC server
        if self._ipc_server is not None:
            self._ipc_server.close()
            await self._ipc_server.wait_closed()
            self._ipc_server = None

        # Close client connection
        if self._client_writer is not None:
            self._client_writer.close()
            self._client_writer = None

        # Clean up socket file
        if self._ipc_socket_path and Path(self._ipc_socket_path).exists():
            Path(self._ipc_socket_path).unlink(missing_ok=True)
            # Remove parent tmpdir if empty
            parent = Path(self._ipc_socket_path).parent
            try:
                parent.rmdir()
            except OSError:
                pass
            self._ipc_socket_path = None

        self._alive = False
        logger.info("ProcessSandbox stopped for session %s", self._session_id)

    async def status(self) -> SandboxStatus:
        uptime = time.monotonic() - self._started_at if self._alive else 0.0
        return SandboxStatus(
            alive=self._alive,
            session_id=self._session_id,
            uptime_seconds=uptime,
        )

    @property
    def is_alive(self) -> bool:
        return self._alive

    async def push_cancel(self) -> None:
        """Push cancel signal to sandbox via IPC."""
        await self._push_message("cancel", {"session_id": self._session_id})

    async def push_hitl_resolution(
        self, hitl_id: str, decision: str, comment: str = ""
    ) -> None:
        """Push HITL resolution to sandbox via IPC."""
        await self._push_message("hitl.resolution", {
            "hitl_id": hitl_id,
            "decision": decision,
            "comment": comment,
        })

    async def _push_message(self, method: str, params: dict) -> None:
        """Send a server-push message to connected sandbox client."""
        if self._client_writer is None:
            logger.debug("No sandbox client connected, cannot push %s", method)
            return
        try:
            msg = {"jsonrpc": "2.0", "method": method, "params": params}
            self._client_writer.write(json.dumps(msg).encode() + b"\n")
            await self._client_writer.drain()
        except Exception as e:
            logger.warning("Failed to push %s to sandbox: %s", method, e)

    async def _exec_bash(self, payload: dict) -> SandboxResult:
        cmd = payload.get("command", "")
        timeout = min(max(payload.get("timeout", 300), 1), 3600)
        started_at = time.monotonic()

        try:
            process = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._workdir,
                env=self._subprocess_env,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=float(timeout)
                )
            except asyncio.TimeoutError:
                try:
                    process.terminate()
                    await process.wait()
                except Exception:
                    pass
                return SandboxResult(
                    success=False,
                    exit_code=-1,
                    error=f"Timeout: command exceeded {timeout} seconds",
                    started_at=started_at,
                    finished_at=time.monotonic(),
                )

            output = stdout.decode(errors="replace")
            err = stderr.decode(errors="replace")
            if err:
                output += f"\n{err}"

            return SandboxResult(
                success=process.returncode == 0,
                output=output.strip(),
                exit_code=process.returncode or 0,
                started_at=started_at,
                finished_at=time.monotonic(),
            )
        except Exception as e:
            return SandboxResult(
                success=False,
                error=str(e),
                started_at=started_at,
                finished_at=time.monotonic(),
            )
```

**Step 5: Run tests**

Run: `uv run pytest tests/test_sandbox/test_process_sandbox_ipc.py tests/test_sandbox/test_process_sandbox.py -v`
Expected: All tests PASS

**Step 6: Commit**

```bash
git add src/everstaff/sandbox/executor.py src/everstaff/sandbox/process_sandbox.py tests/test_sandbox/test_process_sandbox_ipc.py
git commit -m "feat: integrate IPC server into ProcessSandbox"
```

---

## Task 13: HITL Resolution Push

**Files:**
- Modify: `src/everstaff/sandbox/ipc/server_handler.py`
- Modify: `src/everstaff/sandbox/entry.py`
- Create: `tests/test_sandbox/test_hitl_resolution.py`

This task wires HITL resolution from orchestrator to sandbox. When a human approves/rejects,
orchestrator pushes resolution via IPC → sandbox receives it and resumes the runtime.

**Step 1: Write the failing tests**

Create `tests/test_sandbox/test_hitl_resolution.py`:

```python
"""Tests for HITL resolution push flow."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from everstaff.sandbox.ipc.server_handler import IpcServerHandler
from everstaff.sandbox.ipc.token_store import EphemeralTokenStore
from everstaff.core.secret_store import SecretStore


@pytest.mark.asyncio
class TestHitlResolution:
    async def test_server_handler_detects_hitl_from_memory_save(self):
        """When memory.save includes status=waiting_for_human, handler should flag it."""
        token_store = EphemeralTokenStore()
        secret_store = SecretStore()
        handler = IpcServerHandler(token_store=token_store, secret_store=secret_store)

        # Mock memory_store on handler
        handler._memory_store = MagicMock()
        handler._memory_store.save = AsyncMock(return_value=None)

        msg = {
            "jsonrpc": "2.0",
            "method": "memory.save",
            "params": {
                "session_id": "s1",
                "messages": [],
                "status": "waiting_for_human",
                "hitl_requests": [{"hitl_id": "h1", "tool_name": "bash", "args": {}}],
            },
            "id": 1,
        }
        result = await handler.handle_message(msg)
        assert result is not None
        # Handler should have called memory_store.save with correct params
        handler._memory_store.save.assert_awaited_once()

    async def test_hitl_resolution_queue_receives_push(self):
        """sandbox entry should receive HITL resolution via IPC push."""
        resolutions: asyncio.Queue = asyncio.Queue()

        # Simulate the on_push handler from entry.py
        handler = lambda params: resolutions.put_nowait(params)
        handler({"hitl_id": "h1", "decision": "approved", "comment": "looks good"})

        resolution = resolutions.get_nowait()
        assert resolution["hitl_id"] == "h1"
        assert resolution["decision"] == "approved"
        assert resolution["comment"] == "looks good"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_sandbox/test_hitl_resolution.py -v`
Expected: FAIL — `_memory_store` attribute not on handler or handler doesn't support hitl detection

**Step 3: Implement HITL detection in IpcServerHandler**

Update `src/everstaff/sandbox/ipc/server_handler.py` — add HITL detection to the `memory.save` handler:

```python
async def _handle_memory_save(self, params: dict) -> dict:
    """Handle memory.save request. Detect HITL status."""
    await self._memory_store.save(**params)

    # Detect HITL request for channel broadcast
    status = params.get("status")
    hitl_requests = params.get("hitl_requests")
    if status == "waiting_for_human" and hitl_requests:
        session_id = params.get("session_id", "")
        if self._on_hitl_detected:
            await self._on_hitl_detected(session_id, hitl_requests)

    return {"ok": True}
```

Add `on_hitl_detected` callback to `IpcServerHandler.__init__`:

```python
def __init__(
    self,
    token_store: EphemeralTokenStore,
    secret_store: SecretStore,
    memory_store: MemoryStore | None = None,
    tracer: TracingBackend | None = None,
    file_store: FileStore | None = None,
    on_hitl_detected: Callable | None = None,
):
    # ...existing init...
    self._on_hitl_detected = on_hitl_detected
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_sandbox/test_hitl_resolution.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/everstaff/sandbox/ipc/server_handler.py src/everstaff/sandbox/entry.py tests/test_sandbox/test_hitl_resolution.py
git commit -m "feat: HITL resolution push via IPC"
```

---

## Task 14: ExecutorManager Idle Timeout

**Files:**
- Modify: `src/everstaff/sandbox/manager.py`
- Modify: `tests/test_sandbox/test_manager.py`

**Step 1: Write the failing tests**

Add to `tests/test_sandbox/test_manager.py`:

```python
async def test_idle_timeout_destroys_executor(self):
    """Executors idle longer than timeout should be destroyed."""
    executor = AsyncMock()
    executor.is_alive = True
    executor.status = AsyncMock(return_value=MagicMock(
        alive=True, uptime_seconds=0
    ))
    executor.stop = AsyncMock()

    factory = MagicMock(return_value=executor)
    store = SecretStore()
    mgr = ExecutorManager(factory=factory, secret_store=store, idle_timeout=1)

    await mgr.get_or_create("s1")
    assert mgr.has_active("s1")

    # Simulate idle check — executor has been idle > timeout
    executor._last_activity = 0  # far in the past
    await mgr.cleanup_idle()
    # After cleanup, idle executor should be destroyed
    executor.stop.assert_awaited()

async def test_no_idle_timeout_by_default(self):
    """Without idle_timeout, cleanup_idle is a no-op."""
    executor = AsyncMock()
    executor.is_alive = True
    executor.stop = AsyncMock()

    factory = MagicMock(return_value=executor)
    store = SecretStore()
    mgr = ExecutorManager(factory=factory, secret_store=store)

    await mgr.get_or_create("s1")
    await mgr.cleanup_idle()
    executor.stop.assert_not_awaited()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_sandbox/test_manager.py::TestExecutorManager::test_idle_timeout_destroys_executor -v`
Expected: FAIL — `idle_timeout` parameter not accepted

**Step 3: Implement**

Update `src/everstaff/sandbox/manager.py`:

```python
class ExecutorManager:
    """Create, cache, and recycle sandbox executors per session."""

    def __init__(
        self,
        factory: Callable[[], "SandboxExecutor"],
        secret_store: "SecretStore",
        idle_timeout: float | None = None,
    ) -> None:
        self._factory = factory
        self._secret_store = secret_store
        self._executors: dict[str, "SandboxExecutor"] = {}
        self._idle_timeout = idle_timeout
        self._last_activity: dict[str, float] = {}

    async def get_or_create(self, session_id: str) -> "SandboxExecutor":
        self._last_activity[session_id] = time.monotonic()
        # ... existing logic ...

    async def destroy(self, session_id: str) -> None:
        self._last_activity.pop(session_id, None)
        # ... existing logic ...

    async def cleanup_idle(self) -> None:
        """Destroy executors that have been idle longer than idle_timeout."""
        if self._idle_timeout is None:
            return
        now = time.monotonic()
        to_destroy = [
            sid for sid, last in self._last_activity.items()
            if now - last > self._idle_timeout and sid in self._executors
        ]
        for sid in to_destroy:
            logger.info("Destroying idle executor for session %s", sid)
            await self.destroy(sid)
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_sandbox/test_manager.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/everstaff/sandbox/manager.py tests/test_sandbox/test_manager.py
git commit -m "feat: add idle timeout cleanup to ExecutorManager"
```

---

## Task 15: DockerSandbox Backend

**Files:**
- Create: `src/everstaff/sandbox/docker_sandbox.py`
- Create: `tests/test_sandbox/test_docker_sandbox.py`

**Step 1: Write the failing tests**

Create `tests/test_sandbox/test_docker_sandbox.py`:

```python
"""Tests for DockerSandbox backend."""
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from everstaff.core.secret_store import SecretStore
from everstaff.sandbox.docker_sandbox import DockerSandbox, DockerSandboxConfig
from everstaff.sandbox.models import SandboxCommand


class TestDockerSandboxConfig:
    def test_defaults(self):
        cfg = DockerSandboxConfig()
        assert cfg.image == "everstaff-sandbox:latest"
        assert cfg.memory_limit == "512m"
        assert cfg.cpu_limit == 1.0
        assert cfg.network_disabled is True

    def test_custom_values(self):
        cfg = DockerSandboxConfig(image="custom:v1", memory_limit="1g", cpu_limit=2.0)
        assert cfg.image == "custom:v1"
        assert cfg.memory_limit == "1g"


@pytest.mark.asyncio
class TestDockerSandbox:
    async def test_start_creates_container(self, tmp_path):
        """start() should create a Docker container with correct mounts."""
        store = SecretStore({"API_KEY": "secret"})
        config = DockerSandboxConfig(image="test-image:latest")
        sandbox = DockerSandbox(
            workdir=tmp_path, secret_store=store, config=config
        )

        with patch("everstaff.sandbox.docker_sandbox.asyncio") as mock_asyncio:
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_proc.communicate = AsyncMock(return_value=(b"container-id-123\n", b""))
            mock_asyncio.create_subprocess_exec = AsyncMock(return_value=mock_proc)
            mock_asyncio.start_unix_server = AsyncMock()

            await sandbox.start("test-session")
            assert sandbox.is_alive
            assert sandbox._container_id == "container-id-123"

            await sandbox.stop()

    async def test_stop_removes_container(self, tmp_path):
        """stop() should remove the Docker container."""
        store = SecretStore()
        config = DockerSandboxConfig()
        sandbox = DockerSandbox(
            workdir=tmp_path, secret_store=store, config=config
        )
        sandbox._alive = True
        sandbox._container_id = "test-container"
        sandbox._session_id = "s1"

        with patch("everstaff.sandbox.docker_sandbox.asyncio") as mock_asyncio:
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_proc.communicate = AsyncMock(return_value=(b"", b""))
            mock_asyncio.create_subprocess_exec = AsyncMock(return_value=mock_proc)

            await sandbox.stop()
            assert not sandbox.is_alive
            # Should have called docker rm
            calls = mock_asyncio.create_subprocess_exec.call_args_list
            assert any("rm" in str(c) for c in calls)

    async def test_push_cancel(self, tmp_path):
        """push_cancel() should send cancel to container via IPC."""
        store = SecretStore()
        sandbox = DockerSandbox(workdir=tmp_path, secret_store=store)
        sandbox._alive = True
        sandbox._client_writer = MagicMock()
        sandbox._client_writer.write = MagicMock()
        sandbox._client_writer.drain = AsyncMock()
        sandbox._session_id = "s1"

        await sandbox.push_cancel()
        sandbox._client_writer.write.assert_called_once()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_sandbox/test_docker_sandbox.py -v`
Expected: FAIL — module `everstaff.sandbox.docker_sandbox` not found

**Step 3: Implement**

Create `src/everstaff/sandbox/docker_sandbox.py`:

```python
"""DockerSandbox -- Docker container-based sandbox backend."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from everstaff.sandbox.executor import SandboxExecutor
from everstaff.sandbox.ipc.server_handler import IpcServerHandler
from everstaff.sandbox.ipc.token_store import EphemeralTokenStore
from everstaff.sandbox.models import SandboxCommand, SandboxResult, SandboxStatus

if TYPE_CHECKING:
    from everstaff.core.secret_store import SecretStore

logger = logging.getLogger(__name__)


@dataclass
class DockerSandboxConfig:
    """Configuration for Docker sandbox containers."""
    image: str = "everstaff-sandbox:latest"
    memory_limit: str = "512m"
    cpu_limit: float = 1.0
    network_disabled: bool = True
    extra_mounts: dict[str, str] = field(default_factory=dict)


class DockerSandbox(SandboxExecutor):
    """Sandbox that runs agent in a Docker container with IPC via bind-mounted socket.

    Lifecycle:
    1. start() → create IPC socket on host, start IPC server, run container
       with bind mounts for workspace + IPC socket
    2. Container runs python -m everstaff.sandbox.entry
    3. Container connects to host IPC socket, authenticates, runs AgentRuntime
    4. stop() → docker rm -f container, cleanup socket
    """

    def __init__(
        self,
        workdir: Path,
        secret_store: "SecretStore",
        config: DockerSandboxConfig | None = None,
    ) -> None:
        self._workdir = workdir
        self._secret_store = secret_store
        self._config = config or DockerSandboxConfig()
        self._session_id: str = ""
        self._alive: bool = False
        self._started_at: float = 0.0
        self._container_id: str | None = None

        # IPC state (same pattern as ProcessSandbox)
        self._ipc_socket_path: str | None = None
        self._ipc_server: asyncio.AbstractServer | None = None
        self._ipc_handler: IpcServerHandler | None = None
        self._ephemeral_token: str | None = None
        self._token_store: EphemeralTokenStore | None = None
        self._client_writer: asyncio.StreamWriter | None = None

    async def start(self, session_id: str) -> None:
        self._session_id = session_id
        self._workdir.mkdir(parents=True, exist_ok=True)

        # Create IPC socket on host
        tmpdir = tempfile.mkdtemp(prefix="everstaff-docker-ipc-")
        self._ipc_socket_path = os.path.join(tmpdir, f"{session_id}.sock")

        # Generate ephemeral token
        self._token_store = EphemeralTokenStore()
        self._ephemeral_token = self._token_store.create(session_id, ttl_seconds=60)

        # Start IPC server on host
        self._ipc_handler = IpcServerHandler(
            token_store=self._token_store,
            secret_store=self._secret_store,
        )
        self._ipc_server = await asyncio.start_unix_server(
            self._handle_connection,
            path=self._ipc_socket_path,
        )

        # Run Docker container
        ipc_dir = str(Path(self._ipc_socket_path).parent)
        cmd = [
            "docker", "run", "-d",
            "--name", f"everstaff-{session_id}",
            "-v", f"{self._workdir}:/work",
            "-v", f"{ipc_dir}:/ipc",
            "-m", self._config.memory_limit,
            f"--cpus={self._config.cpu_limit}",
        ]
        if self._config.network_disabled:
            cmd.append("--network=none")
        for host_path, container_path in self._config.extra_mounts.items():
            cmd.extend(["-v", f"{host_path}:{container_path}"])
        cmd.extend([
            self._config.image,
            "python", "-m", "everstaff.sandbox.entry",
            "--socket-path", f"/ipc/{session_id}.sock",
            "--token", self._ephemeral_token,
            "--session-id", session_id,
            "--agent-spec", "{}",  # Will be provided by orchestrator
            "--workspace-dir", "/work",
        ])

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            raise RuntimeError(f"Docker run failed: {stderr.decode()}")

        self._container_id = stdout.decode().strip()
        self._alive = True
        self._started_at = time.monotonic()
        logger.info("DockerSandbox started container %s for session %s",
                     self._container_id, session_id)

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self._client_writer = writer
        try:
            async for line in reader:
                msg = json.loads(line)
                response = await self._ipc_handler.handle_message(msg)
                if response is not None:
                    writer.write(json.dumps(response).encode() + b"\n")
                    await writer.drain()
        except Exception as e:
            logger.debug("Docker IPC connection closed: %s", e)
        finally:
            self._client_writer = None
            writer.close()

    async def execute(self, command: SandboxCommand) -> SandboxResult:
        """Execute command inside Docker container via docker exec."""
        if not self._alive or not self._container_id:
            return SandboxResult(success=False, error="Sandbox not running")

        if command.type == "bash":
            return await self._exec_bash_docker(command.payload)
        return SandboxResult(success=False, error=f"Unknown command type: {command.type}")

    async def stop(self) -> None:
        # Stop and remove container
        if self._container_id:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "docker", "rm", "-f", self._container_id,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await proc.communicate()
            except Exception as e:
                logger.warning("Failed to remove container %s: %s", self._container_id, e)
            self._container_id = None

        # Close IPC server
        if self._ipc_server is not None:
            self._ipc_server.close()
            await self._ipc_server.wait_closed()
            self._ipc_server = None

        if self._client_writer is not None:
            self._client_writer.close()
            self._client_writer = None

        # Clean up socket
        if self._ipc_socket_path and Path(self._ipc_socket_path).exists():
            Path(self._ipc_socket_path).unlink(missing_ok=True)
            parent = Path(self._ipc_socket_path).parent
            try:
                parent.rmdir()
            except OSError:
                pass
            self._ipc_socket_path = None

        self._alive = False
        logger.info("DockerSandbox stopped for session %s", self._session_id)

    async def status(self) -> SandboxStatus:
        uptime = time.monotonic() - self._started_at if self._alive else 0.0
        return SandboxStatus(
            alive=self._alive,
            session_id=self._session_id,
            uptime_seconds=uptime,
        )

    @property
    def is_alive(self) -> bool:
        return self._alive

    async def push_cancel(self) -> None:
        await self._push_message("cancel", {"session_id": self._session_id})

    async def push_hitl_resolution(
        self, hitl_id: str, decision: str, comment: str = ""
    ) -> None:
        await self._push_message("hitl.resolution", {
            "hitl_id": hitl_id,
            "decision": decision,
            "comment": comment,
        })

    async def _push_message(self, method: str, params: dict) -> None:
        if self._client_writer is None:
            return
        try:
            msg = {"jsonrpc": "2.0", "method": method, "params": params}
            self._client_writer.write(json.dumps(msg).encode() + b"\n")
            await self._client_writer.drain()
        except Exception as e:
            logger.warning("Failed to push %s to docker sandbox: %s", method, e)

    async def _exec_bash_docker(self, payload: dict) -> SandboxResult:
        """Execute bash command inside Docker container."""
        cmd_str = payload.get("command", "")
        timeout = min(max(payload.get("timeout", 300), 1), 3600)
        started_at = time.monotonic()

        try:
            process = await asyncio.create_subprocess_exec(
                "docker", "exec", self._container_id, "sh", "-c", cmd_str,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=float(timeout)
                )
            except asyncio.TimeoutError:
                # Kill the exec process
                try:
                    process.terminate()
                    await process.wait()
                except Exception:
                    pass
                return SandboxResult(
                    success=False, exit_code=-1,
                    error=f"Timeout: command exceeded {timeout} seconds",
                    started_at=started_at, finished_at=time.monotonic(),
                )

            output = stdout.decode(errors="replace")
            err = stderr.decode(errors="replace")
            if err:
                output += f"\n{err}"

            return SandboxResult(
                success=process.returncode == 0,
                output=output.strip(),
                exit_code=process.returncode or 0,
                started_at=started_at, finished_at=time.monotonic(),
            )
        except Exception as e:
            return SandboxResult(
                success=False, error=str(e),
                started_at=started_at, finished_at=time.monotonic(),
            )
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_sandbox/test_docker_sandbox.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add src/everstaff/sandbox/docker_sandbox.py tests/test_sandbox/test_docker_sandbox.py
git commit -m "feat: add DockerSandbox backend with IPC via bind-mounted socket"
```

---

## Task 16: Full Integration Test Run

**Step 1: Run all sandbox tests**

Run: `uv run pytest tests/test_sandbox/ -v`
Expected: All tests PASS

**Step 2: Run all project tests (sanity check)**

Run: `uv run pytest tests/test_core/ tests/test_sandbox/ tests/test_builtin_tools/ tests/test_mcp_client/ -v`
Expected: All tests PASS (except pre-existing API test failures unrelated to our changes)

**Step 3: Commit if any fixups needed**

---

## Summary

| Task | Phase | Component | Files Created/Modified |
|------|-------|-----------|----------------------|
| 0 | 1-2 supplement | SandboxResult timestamps | models.py, process_sandbox.py |
| 1 | 3 | JSON-RPC protocol models | ipc/protocol.py |
| 2 | 3 | IpcChannel ABC + EphemeralTokenStore | ipc/channel.py, token_store.py |
| 3 | 3 | UnixSocketChannel + Server | ipc/unix_socket.py |
| 4 | 4 | ProxyMemoryStore | proxy/memory_store.py |
| 5 | 4 | ProxyTracer + ProxyFileStore | proxy/tracer.py, proxy/file_store.py |
| 6 | 4 | SandboxEnvironment | environment.py |
| 7 | 5 | IPC Server Handler | ipc/server_handler.py |
| 8 | 5 | E2E Integration Test | test_integration.py |
| 9 | 5 | ExecutorManager cancel support | manager.py |
| 10 | — | Checkpoint: full test run | — |
| 11 | 5 | Sandbox Entry Point | entry.py |
| 12 | 5 | ProcessSandbox IPC Integration | process_sandbox.py, executor.py |
| 13 | 5 | HITL Resolution Push | server_handler.py, entry.py |
| 14 | 5 | ExecutorManager Idle Timeout | manager.py |
| 15 | 6 | DockerSandbox Backend | docker_sandbox.py |
| 16 | — | Final full test run | — |

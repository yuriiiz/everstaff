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

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

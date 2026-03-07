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

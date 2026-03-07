"""Tests for Mem0ExtractionStrategy."""
import pytest
from unittest.mock import AsyncMock

from everstaff.protocols import Message


def _make_messages(n: int) -> list[Message]:
    msgs = []
    for i in range(n):
        role = "user" if i % 2 == 0 else "assistant"
        msgs.append(Message(role=role, content=f"Message {i}"))
    return msgs


@pytest.mark.asyncio
class TestMem0ExtractionStrategy:
    async def test_compress_extracts_old_and_keeps_recent(self):
        from everstaff.memory.strategies import Mem0ExtractionStrategy

        mock_client = AsyncMock()
        mock_client.add = AsyncMock(return_value=[])

        strategy = Mem0ExtractionStrategy(
            mock_client, user_id="u1", agent_id="a1", session_id="s1", keep_last=5,
        )

        messages = _make_messages(10)
        result = await strategy.compress(messages)

        assert len(result) == 5
        assert result[0].content == "Message 5"

        mock_client.add.assert_called_once()
        call_args = mock_client.add.call_args
        extracted = call_args[0][0]
        assert len(extracted) == 5
        assert call_args[1] == {"user_id": "u1", "agent_id": "a1", "run_id": "s1"}

    async def test_compress_skips_empty_content_messages(self):
        from everstaff.memory.strategies import Mem0ExtractionStrategy

        mock_client = AsyncMock()
        mock_client.add = AsyncMock(return_value=[])

        strategy = Mem0ExtractionStrategy(mock_client, keep_last=2)

        messages = [
            Message(role="assistant", content=None, tool_calls=[{"id": "tc1", "type": "function", "function": {"name": "foo", "arguments": "{}"}}]),
            Message(role="tool", content="result", tool_call_id="tc1"),
            Message(role="user", content="hello"),
            Message(role="assistant", content="hi"),
        ]
        result = await strategy.compress(messages)

        assert len(result) == 2
        call_args = mock_client.add.call_args[0][0]
        assert len(call_args) == 1
        assert call_args[0]["content"] == "result"

    async def test_compress_fallback_on_mem0_failure(self):
        from everstaff.memory.strategies import Mem0ExtractionStrategy

        mock_client = AsyncMock()
        mock_client.add = AsyncMock(side_effect=Exception("mem0 down"))

        strategy = Mem0ExtractionStrategy(mock_client, keep_last=5)

        messages = _make_messages(10)
        result = await strategy.compress(messages)

        assert len(result) == 5
        assert result[0].content == "Message 5"

    async def test_compress_cleans_orphan_tool_results(self):
        from everstaff.memory.strategies import Mem0ExtractionStrategy

        mock_client = AsyncMock()
        mock_client.add = AsyncMock(return_value=[])

        strategy = Mem0ExtractionStrategy(mock_client, keep_last=3)

        messages = [
            Message(role="assistant", content=None, tool_calls=[{"id": "tc_old", "type": "function", "function": {"name": "foo", "arguments": "{}"}}]),
            Message(role="tool", content="old result", tool_call_id="tc_old"),
            Message(role="tool", content="orphan result", tool_call_id="tc_gone"),
            Message(role="user", content="hello"),
            Message(role="assistant", content="hi"),
        ]
        result = await strategy.compress(messages)

        assert len(result) == 2
        assert result[0].content == "hello"
        assert result[1].content == "hi"

    async def test_no_extraction_when_no_old_messages(self):
        from everstaff.memory.strategies import Mem0ExtractionStrategy

        mock_client = AsyncMock()
        strategy = Mem0ExtractionStrategy(mock_client, keep_last=20)

        messages = _make_messages(5)
        result = await strategy.compress(messages)

        assert len(result) == 5
        mock_client.add.assert_not_called()

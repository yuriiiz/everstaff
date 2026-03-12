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

        # Use a small max_tokens so that only recent messages fit within
        # 40% budget; "Message N" ~ 2 tokens each, 10 messages ~ 20 tokens,
        # 40% of 25 = 10 tokens ~ 5 messages
        strategy = Mem0ExtractionStrategy(
            mock_client, user_id="u1", agent_id="a1", session_id="s1", max_tokens=25,
        )

        messages = _make_messages(10)
        result = await strategy.compress(messages)

        # Some messages should have been compacted away
        assert len(result) < 10
        # Most recent messages should be kept
        assert result[-1].content == "Message 9"

        # mem0 should have been called with the dropped messages
        mock_client.add.assert_called_once()
        call_args = mock_client.add.call_args
        extracted = call_args[0][0]
        assert len(extracted) > 0
        assert call_args[1] == {"user_id": "u1", "agent_id": "a1", "run_id": "s1"}

    async def test_compress_skips_empty_content_messages(self):
        from everstaff.memory.strategies import Mem0ExtractionStrategy

        mock_client = AsyncMock()
        mock_client.add = AsyncMock(return_value=[])

        # Very small max_tokens to force compaction
        strategy = Mem0ExtractionStrategy(mock_client, max_tokens=10)

        messages = [
            Message(role="assistant", content=None, tool_calls=[{"id": "tc1", "type": "function", "function": {"name": "foo", "arguments": "{}"}}]),
            Message(role="tool", content="result", tool_call_id="tc1"),
            Message(role="user", content="hello"),
            Message(role="assistant", content="hi"),
        ]
        result = await strategy.compress(messages)

        # Recent messages should be kept; old ones extracted to mem0
        # The extracted messages to mem0 should only have user/assistant with content
        if mock_client.add.called:
            call_args = mock_client.add.call_args[0][0]
            for m in call_args:
                assert m["content"] is not None
                assert m["role"] in ("user", "assistant")

    async def test_compress_fallback_on_mem0_failure(self):
        from everstaff.memory.strategies import Mem0ExtractionStrategy

        mock_client = AsyncMock()
        mock_client.add = AsyncMock(side_effect=Exception("mem0 down"))

        strategy = Mem0ExtractionStrategy(mock_client, max_tokens=25)

        messages = _make_messages(10)
        result = await strategy.compress(messages)

        # Even on mem0 failure, compaction should still work
        assert len(result) < 10
        assert result[-1].content == "Message 9"

    async def test_compress_cleans_orphan_tool_results(self):
        from everstaff.memory.strategies import Mem0ExtractionStrategy

        mock_client = AsyncMock()
        mock_client.add = AsyncMock(return_value=[])

        # Small max_tokens to force compaction
        strategy = Mem0ExtractionStrategy(mock_client, max_tokens=15)

        messages = [
            Message(role="assistant", content=None, tool_calls=[{"id": "tc_old", "type": "function", "function": {"name": "foo", "arguments": "{}"}}]),
            Message(role="tool", content="old result", tool_call_id="tc_old"),
            Message(role="tool", content="orphan result", tool_call_id="tc_gone"),
            Message(role="user", content="hello"),
            Message(role="assistant", content="hi"),
        ]
        result = await strategy.compress(messages)

        # The orphan tool result (tc_gone) should never appear in the result
        orphan_results = [m for m in result if m.role == "tool" and m.tool_call_id == "tc_gone"]
        assert len(orphan_results) == 0

    async def test_no_extraction_when_no_old_messages(self):
        from everstaff.memory.strategies import Mem0ExtractionStrategy

        mock_client = AsyncMock()
        # Large max_tokens so nothing gets compacted
        strategy = Mem0ExtractionStrategy(mock_client, max_tokens=100_000)

        messages = _make_messages(5)
        result = await strategy.compress(messages)

        # All messages fit in budget, nothing compacted
        assert len(result) == 5
        mock_client.add.assert_not_called()

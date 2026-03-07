"""Tests for Mem0Hook — search refresh + session-end flush."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from everstaff.protocols import Message, HookContext


def _make_hook_ctx() -> HookContext:
    return HookContext(session_id="s1", agent_name="test-agent")


@pytest.mark.asyncio
class TestMem0HookOnLlmStart:
    async def test_refreshes_provider_with_last_user_message(self):
        from everstaff.memory.mem0_hook import Mem0Hook

        mock_provider = MagicMock()
        mock_provider.refresh = AsyncMock()

        hook = Mem0Hook(
            mem0_provider=mock_provider,
            mem0_client=AsyncMock(),
            memory_store=AsyncMock(),
        )

        messages = [
            Message(role="user", content="first question"),
            Message(role="assistant", content="answer"),
            Message(role="user", content="second question"),
        ]
        result = await hook.on_llm_start(_make_hook_ctx(), messages)

        mock_provider.set_query.assert_called_once_with("second question")
        mock_provider.refresh.assert_called_once()
        assert result == messages

    async def test_skips_when_no_user_message(self):
        from everstaff.memory.mem0_hook import Mem0Hook

        mock_provider = MagicMock()
        mock_provider.refresh = AsyncMock()

        hook = Mem0Hook(
            mem0_provider=mock_provider,
            mem0_client=AsyncMock(),
            memory_store=AsyncMock(),
        )

        messages = [Message(role="assistant", content="hello")]
        result = await hook.on_llm_start(_make_hook_ctx(), messages)

        mock_provider.set_query.assert_not_called()
        assert result == messages


@pytest.mark.asyncio
class TestMem0HookOnSessionEnd:
    async def test_flushes_messages_to_mem0(self):
        from everstaff.memory.mem0_hook import Mem0Hook

        mock_client = AsyncMock()
        mock_client.add = AsyncMock(return_value=[])

        mock_memory = AsyncMock()
        mock_memory.load = AsyncMock(return_value=[
            Message(role="user", content="hello"),
            Message(role="assistant", content="hi"),
            Message(role="assistant", content=None, tool_calls=[{"id": "tc1"}]),
            Message(role="tool", content="result", tool_call_id="tc1"),
        ])

        hook = Mem0Hook(
            mem0_provider=MagicMock(),
            mem0_client=mock_client,
            memory_store=mock_memory,
            user_id="u1",
            agent_id="a1",
        )

        await hook.on_session_end(_make_hook_ctx(), "bye")

        mock_client.add.assert_called_once()
        extracted = mock_client.add.call_args[0][0]
        assert len(extracted) == 2
        assert extracted[0] == {"role": "user", "content": "hello"}
        assert extracted[1] == {"role": "assistant", "content": "hi"}

    async def test_session_end_failure_does_not_raise(self):
        from everstaff.memory.mem0_hook import Mem0Hook

        mock_client = AsyncMock()
        mock_client.add = AsyncMock(side_effect=Exception("boom"))

        mock_memory = AsyncMock()
        mock_memory.load = AsyncMock(return_value=[
            Message(role="user", content="hello"),
        ])

        hook = Mem0Hook(
            mem0_provider=MagicMock(),
            mem0_client=mock_client,
            memory_store=mock_memory,
        )

        await hook.on_session_end(_make_hook_ctx(), "bye")

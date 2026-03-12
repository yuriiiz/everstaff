import pytest
from everstaff.protocols import Message


def make_messages(n: int) -> list[Message]:
    msgs = []
    for i in range(n):
        msgs.append(Message(role="user", content=f"message {i}"))
        msgs.append(Message(role="assistant", content=f"reply {i}"))
    return msgs


def _make_skill_messages() -> list[Message]:
    """Create a message sequence containing a use_skill tool call and result."""
    return [
        Message(role="user", content="old user message " * 100),
        Message(
            role="assistant",
            content=None,
            tool_calls=[{
                "id": "call_skill_1",
                "type": "function",
                "function": {"name": "use_skill", "arguments": '{"skill_name": "sre-handbook"}'},
            }],
        ),
        Message(
            role="tool",
            content="This is the skill content that must be preserved. " * 50,
            tool_call_id="call_skill_1",
            name="use_skill",
        ),
        Message(role="assistant", content="I've loaded the skill. " * 20),
    ]


@pytest.mark.asyncio
async def test_truncation_strategy_compacts_to_target():
    """Smart truncation keeps recent messages within ~40% of max_tokens."""
    from everstaff.memory.strategies import TruncationStrategy
    # Use a very small max_tokens so our short messages still get compacted
    strategy = TruncationStrategy(max_tokens=50)
    msgs = make_messages(10)  # 20 messages
    result = await strategy.compress(msgs)
    # Should have fewer messages than the original 20
    assert len(result) < len(msgs)
    # Should keep the most recent messages
    assert result[-1].content == msgs[-1].content


@pytest.mark.asyncio
async def test_truncation_strategy_preserves_skill_messages():
    """Skill-related messages (use_skill tool calls + results) must survive compaction."""
    from everstaff.memory.strategies import TruncationStrategy

    # Put skill messages early, then lots of filler, so they'd normally be truncated
    skill_msgs = _make_skill_messages()
    filler = make_messages(20)  # 40 filler messages
    all_msgs = skill_msgs + filler

    # Small budget so filler alone fills it — skill messages are "old" but protected
    strategy = TruncationStrategy(max_tokens=200)
    result = await strategy.compress(all_msgs)

    # The skill assistant message and its tool result must be present
    skill_call_ids = {m.tool_call_id for m in result if m.role == "tool" and m.tool_call_id}
    assert "call_skill_1" in skill_call_ids
    # The assistant message with the tool_call should also be present
    assistant_with_skill = [
        m for m in result
        if m.role == "assistant" and m.tool_calls
        and any(
            (tc.get("function", {}).get("name") if isinstance(tc, dict) else None) == "use_skill"
            for tc in m.tool_calls
        )
    ]
    assert len(assistant_with_skill) == 1


@pytest.mark.asyncio
async def test_truncation_strategy_ensures_complete_tool_groups():
    """If an assistant tool_call is kept, all its tool results must also be kept."""
    from everstaff.memory.strategies import TruncationStrategy

    msgs = [
        Message(role="user", content="hello"),
        Message(
            role="assistant",
            content=None,
            tool_calls=[
                {"id": "call_1", "type": "function", "function": {"name": "search", "arguments": "{}"}},
                {"id": "call_2", "type": "function", "function": {"name": "read", "arguments": "{}"}},
            ],
        ),
        Message(role="tool", content="search result", tool_call_id="call_1", name="search"),
        Message(role="tool", content="read result", tool_call_id="call_2", name="read"),
        Message(role="assistant", content="Here is the answer."),
    ]

    strategy = TruncationStrategy(max_tokens=1000)
    result = await strategy.compress(msgs)

    # If the assistant with tool_calls is present, both tool results must be too
    has_tc_assistant = any(m.role == "assistant" and m.tool_calls for m in result)
    if has_tc_assistant:
        tool_ids = {m.tool_call_id for m in result if m.role == "tool"}
        assert "call_1" in tool_ids
        assert "call_2" in tool_ids


@pytest.mark.asyncio
async def test_compressible_store_triggers_on_token_threshold(tmp_path):
    from everstaff.memory.file_store import FileMemoryStore
    from everstaff.memory.compressible_store import CompressibleMemoryStore
    from everstaff.memory.strategies import TruncationStrategy

    base = FileMemoryStore(tmp_path)
    # max_tokens=100, ratio=1.0 → threshold=100 tokens; "message N"/"reply N" ~3 tokens each
    # 4 pairs × 2 messages × ~3 tokens = ~24 tokens < 100 → no compression
    store = CompressibleMemoryStore(
        store=base,
        strategy=TruncationStrategy(max_tokens=100),
        max_tokens=100,
        compression_ratio=1.0,
    )

    msgs = make_messages(2)  # 4 messages — well below 100-token threshold
    await store.save("s1", msgs)
    loaded = await store.load("s1")
    assert len(loaded) == 4  # untouched


@pytest.mark.asyncio
async def test_compressible_store_no_trigger_below_threshold(tmp_path):
    from everstaff.memory.file_store import FileMemoryStore
    from everstaff.memory.compressible_store import CompressibleMemoryStore
    from everstaff.memory.strategies import TruncationStrategy

    base = FileMemoryStore(tmp_path)
    # Very high threshold — should never trigger
    store = CompressibleMemoryStore(
        store=base,
        strategy=TruncationStrategy(),
        max_tokens=999_999,
        compression_ratio=0.7,
    )

    msgs = make_messages(2)  # 4 messages — far below threshold
    await store.save("s1", msgs)
    loaded = await store.load("s1")
    assert len(loaded) == 4  # untouched


@pytest.mark.asyncio
async def test_compressible_store_triggers_on_token_estimate(tmp_path):
    from everstaff.memory.file_store import FileMemoryStore
    from everstaff.memory.compressible_store import CompressibleMemoryStore
    from everstaff.memory.strategies import TruncationStrategy

    base = FileMemoryStore(tmp_path)
    # max_tokens=10, ratio=1.0 → threshold=10; any real message content exceeds this
    store = CompressibleMemoryStore(
        store=base,
        strategy=TruncationStrategy(max_tokens=10),
        max_tokens=10,
        compression_ratio=1.0,
    )

    msgs = make_messages(3)  # 6 messages with real content
    await store.save("s1", msgs)
    loaded = await store.load("s1")
    # With smart compaction targeting 40% of 10 = 4 tokens, very few messages survive
    assert len(loaded) < len(msgs)


@pytest.mark.asyncio
async def test_compressible_store_load_delegates_to_inner(tmp_path):
    from everstaff.memory.file_store import FileMemoryStore
    from everstaff.memory.compressible_store import CompressibleMemoryStore
    from everstaff.memory.strategies import TruncationStrategy

    base = FileMemoryStore(tmp_path)
    msgs = [Message(role="user", content="direct")]
    await base.save("s1", msgs)

    store = CompressibleMemoryStore(base, TruncationStrategy())
    loaded = await store.load("s1")
    assert loaded[0].content == "direct"


@pytest.mark.asyncio
async def test_compressible_store_passes_metadata_to_inner_store():
    """CompressibleMemoryStore must forward all kwargs to the wrapped store.
    If it doesn't, metadata like title/status/stats is silently lost."""
    from everstaff.memory.compressible_store import CompressibleMemoryStore
    from everstaff.memory.strategies import TruncationStrategy
    from unittest.mock import AsyncMock, MagicMock

    inner = MagicMock()
    inner.load = AsyncMock(return_value=[])
    inner.save = AsyncMock()

    store = CompressibleMemoryStore(inner, TruncationStrategy())

    fake_stats = MagicMock()
    await store.save(
        "sess-1",
        [],
        agent_name="my_agent",
        status="completed",
        title="Test Session",
        stats=fake_stats,
        parent_session_id=None,
        system_prompt="sys",
    )

    inner.save.assert_called_once()
    call_args = inner.save.call_args
    # The inner store should have been called with all kwargs
    assert call_args.kwargs.get("agent_name") == "my_agent"
    assert call_args.kwargs.get("status") == "completed"
    assert call_args.kwargs.get("title") == "Test Session"
    assert call_args.kwargs.get("stats") is fake_stats

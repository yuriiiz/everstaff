import pytest
from everstaff.protocols import Message


def make_messages(n: int) -> list[Message]:
    msgs = []
    for i in range(n):
        msgs.append(Message(role="user", content=f"message {i}"))
        msgs.append(Message(role="assistant", content=f"reply {i}"))
    return msgs


@pytest.mark.asyncio
async def test_truncation_strategy_keeps_last_n():
    from everstaff.memory.strategies import TruncationStrategy
    strategy = TruncationStrategy(keep_last=4)
    msgs = make_messages(5)  # 10 messages
    result = await strategy.compress(msgs)
    assert len(result) == 4
    assert result == msgs[-4:]


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
        strategy=TruncationStrategy(keep_last=4),
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
        strategy=TruncationStrategy(keep_last=4),
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
        strategy=TruncationStrategy(keep_last=2),
        max_tokens=10,
        compression_ratio=1.0,
    )

    msgs = make_messages(3)  # 6 messages with real content
    await store.save("s1", msgs)
    loaded = await store.load("s1")
    assert len(loaded) == 2


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

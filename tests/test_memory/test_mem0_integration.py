"""Integration test: full mem0 compression + retrieval round trip."""
import pytest
from unittest.mock import AsyncMock

from everstaff.protocols import Message


@pytest.mark.asyncio
async def test_full_round_trip_compression_and_retrieval(tmp_path):
    """Simulate: messages exceed threshold -> compress extracts to mem0 -> next turn retrieves."""
    from everstaff.memory.strategies import Mem0ExtractionStrategy
    from everstaff.memory.mem0_provider import Mem0Provider
    from everstaff.memory.compressible_store import CompressibleMemoryStore
    from everstaff.memory.file_store import FileMemoryStore
    from everstaff.storage.local import LocalFileStore

    # Setup mock mem0 client
    mock_mem0 = AsyncMock()
    mock_mem0.add = AsyncMock(return_value=[{"id": "m1", "event": "ADD"}])
    mock_mem0.search = AsyncMock(return_value=[
        {"memory": "User prefers Python over JavaScript", "score": 0.95},
    ])

    # Build store with very low threshold to trigger compression
    file_store = LocalFileStore(str(tmp_path))
    mem_store = FileMemoryStore(file_store)
    strategy = Mem0ExtractionStrategy(
        mock_mem0, user_id="u1", agent_id="agent-1", session_id="s1", max_tokens=100,
    )
    store = CompressibleMemoryStore(mem_store, strategy, max_tokens=100, compression_ratio=0.1)

    # Create messages that exceed the token threshold (need many chars)
    messages = [
        Message(role="user", content="I love Python programming " * 20),
        Message(role="assistant", content="Python is great! " * 20),
        Message(role="user", content="Tell me about JavaScript " * 20),
        Message(role="assistant", content="JavaScript is versatile " * 20),
        Message(role="user", content="I prefer Python"),
        Message(role="assistant", content="Noted!"),
        Message(role="user", content="What else?"),
        Message(role="assistant", content="Let me help."),
        Message(role="user", content="Thanks"),
        Message(role="assistant", content="You're welcome!"),
    ]

    # Save should trigger compression
    await store.save("s1", messages, agent_name="agent-1")

    # Verify mem0.add was called with old messages
    assert mock_mem0.add.called
    extracted = mock_mem0.add.call_args[0][0]
    # Should have extracted the first long messages
    assert len(extracted) > 0

    # Verify stored messages are truncated
    loaded = await store.load("s1")
    assert len(loaded) < len(messages)

    # Now simulate retrieval for next turn
    provider = Mem0Provider(mock_mem0, user_id="u1", agent_id="agent-1")
    provider.set_query("What language do I prefer?")
    await provider.refresh()

    injection = provider.get_prompt_injection()
    assert "[Long-term memory]" in injection
    assert "Python over JavaScript" in injection


@pytest.mark.asyncio
async def test_mem0_disabled_uses_truncation(tmp_path):
    """When mem0 is disabled, compression uses plain TruncationStrategy."""
    from everstaff.memory.strategies import TruncationStrategy
    from everstaff.memory.compressible_store import CompressibleMemoryStore
    from everstaff.memory.file_store import FileMemoryStore
    from everstaff.storage.local import LocalFileStore

    file_store = LocalFileStore(str(tmp_path))
    mem_store = FileMemoryStore(file_store)
    strategy = TruncationStrategy(max_tokens=100)
    store = CompressibleMemoryStore(mem_store, strategy, max_tokens=100, compression_ratio=0.1)

    messages = [
        Message(role="user", content="msg " * 50),
        Message(role="assistant", content="reply " * 50),
        Message(role="user", content="short"),
        Message(role="assistant", content="ok"),
        Message(role="user", content="last"),
    ]

    await store.save("s1", messages, agent_name="test")
    loaded = await store.load("s1")
    assert len(loaded) < len(messages)

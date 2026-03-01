import pytest
from everstaff.protocols import PermissionResult


@pytest.mark.asyncio
async def test_null_tracer_accepts_any_event():
    from everstaff.nulls import NullTracer
    from everstaff.protocols import TraceEvent
    tracer = NullTracer()
    tracer.on_event(TraceEvent(kind="llm_start", session_id="s1"))  # must not raise


@pytest.mark.asyncio
async def test_allow_all_checker_always_allows():
    from everstaff.nulls import AllowAllChecker
    checker = AllowAllChecker()
    result = checker.check("any_tool", {"arg": "val"})
    assert result.allowed


@pytest.mark.asyncio
async def test_null_skill_provider_returns_empty():
    from everstaff.nulls import NullSkillProvider
    provider = NullSkillProvider()
    assert provider.get_tools() == []
    assert provider.get_prompt_injection() == ""


@pytest.mark.asyncio
async def test_null_memory_store_roundtrip():
    from everstaff.nulls import InMemoryStore
    from everstaff.protocols import Message
    store = InMemoryStore()
    msgs = [Message(role="user", content="hello")]
    await store.save("sess1", msgs)
    loaded = await store.load("sess1")
    assert len(loaded) == 1
    assert loaded[0].content == "hello"


@pytest.mark.asyncio
async def test_null_memory_store_empty_on_miss():
    from everstaff.nulls import InMemoryStore
    store = InMemoryStore()
    loaded = await store.load("nonexistent")
    assert loaded == []


@pytest.mark.asyncio
async def test_null_mcp_provider_aclose_is_noop():
    """NullMcpProvider.aclose() must complete without error."""
    from everstaff.nulls import NullMcpProvider
    provider = NullMcpProvider()
    await provider.aclose()  # must not raise


@pytest.mark.asyncio
async def test_in_memory_store_working_memory():
    from everstaff.nulls import InMemoryStore
    from everstaff.protocols import WorkingState
    store = InMemoryStore()
    state = await store.working_load("agent-1")
    assert state == WorkingState()

    state.pending_items = ["task1"]
    await store.working_save("agent-1", state)
    loaded = await store.working_load("agent-1")
    assert loaded.pending_items == ["task1"]


@pytest.mark.asyncio
async def test_in_memory_store_episodic_memory():
    from everstaff.nulls import InMemoryStore
    from everstaff.protocols import Episode
    store = InMemoryStore()
    ep = Episode(timestamp="2026-02-28T09:00:00Z", trigger="cron", action="test", result="ok")
    await store.episode_append("agent-1", ep)
    episodes = await store.episode_query("agent-1")
    assert len(episodes) == 1
    assert episodes[0].action == "test"


@pytest.mark.asyncio
async def test_in_memory_store_semantic_memory():
    from everstaff.nulls import InMemoryStore
    store = InMemoryStore()
    assert await store.semantic_read("agent-1") == ""
    await store.semantic_write("agent-1", "patterns", "# Work Patterns\n...")
    content = await store.semantic_read("agent-1", "patterns")
    assert "Work Patterns" in content
    topics = await store.semantic_list("agent-1")
    assert "patterns" in topics

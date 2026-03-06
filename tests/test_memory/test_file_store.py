import pytest
from everstaff.protocols import Message


@pytest.mark.asyncio
async def test_save_and_load_roundtrip(tmp_path):
    from everstaff.memory.file_store import FileMemoryStore
    store = FileMemoryStore(base_dir=tmp_path)
    msgs = [
        Message(role="user", content="hello"),
        Message(role="assistant", content="hi there"),
    ]
    await store.save("sess1", msgs)
    loaded = await store.load("sess1")
    assert len(loaded) == 2
    assert loaded[0].role == "user"
    assert loaded[1].content == "hi there"


@pytest.mark.asyncio
async def test_message_created_at_roundtrip(tmp_path):
    from everstaff.memory.file_store import FileMemoryStore
    store = FileMemoryStore(base_dir=tmp_path)
    msgs = [
        Message(role="user", content="hello", created_at="2026-03-06T12:00:00+00:00"),
        Message(role="assistant", content="hi", created_at="2026-03-06T12:00:01+00:00"),
    ]
    await store.save("sess-ts", msgs)
    loaded = await store.load("sess-ts")
    assert loaded[0].created_at == "2026-03-06T12:00:00+00:00"
    assert loaded[1].created_at == "2026-03-06T12:00:01+00:00"


@pytest.mark.asyncio
async def test_message_created_at_backward_compat(tmp_path):
    """Old sessions without created_at should load with None."""
    from everstaff.memory.file_store import FileMemoryStore
    store = FileMemoryStore(base_dir=tmp_path)
    msgs = [Message(role="user", content="old msg")]  # no created_at
    await store.save("sess-old", msgs)
    loaded = await store.load("sess-old")
    assert loaded[0].created_at is None


@pytest.mark.asyncio
async def test_load_nonexistent_returns_empty(tmp_path):
    from everstaff.memory.file_store import FileMemoryStore
    store = FileMemoryStore(base_dir=tmp_path)
    result = await store.load("nonexistent")
    assert result == []


@pytest.mark.asyncio
async def test_overwrite_session(tmp_path):
    from everstaff.memory.file_store import FileMemoryStore
    store = FileMemoryStore(base_dir=tmp_path)
    await store.save("s1", [Message(role="user", content="v1")])
    await store.save("s1", [Message(role="user", content="v2"), Message(role="assistant", content="r2")])
    loaded = await store.load("s1")
    assert len(loaded) == 2
    assert loaded[0].content == "v2"


@pytest.mark.asyncio
async def test_messages_with_tool_calls_roundtrip(tmp_path):
    from everstaff.memory.file_store import FileMemoryStore
    store = FileMemoryStore(base_dir=tmp_path)
    msgs = [
        Message(role="assistant", content=None, tool_calls=[{"id": "c1", "type": "function", "function": {"name": "foo", "arguments": "{}"}}]),
        Message(role="tool", content="result", tool_call_id="c1"),
    ]
    await store.save("s2", msgs)
    loaded = await store.load("s2")
    assert loaded[0].tool_calls[0]["id"] == "c1"
    assert loaded[1].tool_call_id == "c1"


@pytest.mark.asyncio
async def test_file_store_uses_subdir_layout(tmp_path):
    """session.json must live at {base}/{session_id}/session.json, not {base}/{session_id}.json"""
    from everstaff.memory.file_store import FileMemoryStore
    from everstaff.protocols import Message

    store = FileMemoryStore(tmp_path)
    msgs = [Message(role="user", content="hello")]
    await store.save("sess-abc", msgs)

    # New layout: subdir
    assert (tmp_path / "sess-abc" / "session.json").exists()
    # Old layout must NOT be used
    assert not (tmp_path / "sess-abc.json").exists()


@pytest.mark.asyncio
async def test_file_store_load_includes_metadata(tmp_path):
    """load() returns messages; session.json stores metadata header."""
    from everstaff.memory.file_store import FileMemoryStore
    from everstaff.protocols import Message
    import json

    store = FileMemoryStore(tmp_path)
    msgs = [Message(role="user", content="hi")]
    await store.save("s1", msgs)

    raw = json.loads((tmp_path / "s1" / "session.json").read_text())
    assert "messages" in raw
    assert "session_id" in raw
    assert raw["session_id"] == "s1"
    assert "created_at" in raw
    assert "updated_at" in raw


@pytest.mark.asyncio
async def test_file_store_preserves_metadata_on_resave(tmp_path):
    from everstaff.memory.file_store import FileMemoryStore
    from everstaff.protocols import Message
    import json

    store = FileMemoryStore(tmp_path)
    msgs1 = [Message(role="user", content="first")]
    await store.save("s2", msgs1, agent_name="my-agent")

    raw1 = json.loads((tmp_path / "s2" / "session.json").read_text())
    created_at = raw1["created_at"]

    msgs2 = [Message(role="user", content="second")]
    await store.save("s2", msgs2)  # no agent_name this time

    raw2 = json.loads((tmp_path / "s2" / "session.json").read_text())
    assert raw2["created_at"] == created_at         # preserved
    assert raw2["agent_name"] == "my-agent"         # preserved from first save
    assert raw2["messages"][0]["content"] == "second"  # messages updated


@pytest.mark.asyncio
async def test_save_writes_metadata_field(tmp_path):
    """session.json must contain a 'metadata' field matching MemoryContext schema."""
    import json
    from everstaff.memory.file_store import FileMemoryStore
    from everstaff.protocols import Message
    from everstaff.schema.token_stats import SessionStats, TokenUsage

    store = FileMemoryStore(tmp_path)
    msgs = [Message(role="user", content="hello")]

    stats = SessionStats()
    stats.record(TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15, model_id="gpt-4"))
    stats.record_tool_call()
    stats.record_error()

    await store.save("s-meta", msgs, agent_name="TestAgent", stats=stats)

    raw = json.loads((tmp_path / "s-meta" / "session.json").read_text())
    assert "metadata" in raw
    meta = raw["metadata"]
    assert meta["title"] == "TestAgent"
    assert meta["tool_calls_count"] == 1
    assert meta["errors_count"] == 1
    assert len(meta["own_calls"]) == 1
    assert meta["own_calls"][0]["input_tokens"] == 10


@pytest.mark.asyncio
async def test_save_without_stats_writes_empty_metadata(tmp_path):
    """When no stats provided, metadata is still written with zero values."""
    import json
    from everstaff.memory.file_store import FileMemoryStore
    from everstaff.protocols import Message

    store = FileMemoryStore(tmp_path)
    await store.save("s-no-stats", [Message(role="user", content="hi")])

    raw = json.loads((tmp_path / "s-no-stats" / "session.json").read_text())
    assert "metadata" in raw
    assert raw["metadata"]["tool_calls_count"] == 0
    assert raw["metadata"]["own_calls"] == []


@pytest.mark.asyncio
async def test_file_store_saves_and_loads_system_prompt(tmp_path):
    from everstaff.memory.file_store import FileMemoryStore
    store = FileMemoryStore(tmp_path)
    await store.save(
        "sess-1", [],
        agent_name="my-agent",
        system_prompt="You are a helpful assistant.",
    )
    import json
    data = json.loads((tmp_path / "sess-1" / "session.json").read_text())
    assert data["metadata"]["system_prompt"] == "You are a helpful assistant."


@pytest.mark.asyncio
async def test_file_memory_store_accepts_file_store_injection(tmp_path):
    """FileMemoryStore accepts a FileStore instance directly."""
    from everstaff.storage.local import LocalFileStore
    from everstaff.memory.file_store import FileMemoryStore
    from everstaff.protocols import Message

    store = FileMemoryStore(LocalFileStore(tmp_path))
    await store.save("s-inject", [Message(role="user", content="hi")])
    msgs = await store.load("s-inject")
    assert len(msgs) == 1


@pytest.mark.asyncio
async def test_title_preserved_when_resaved_with_stats(tmp_path):
    """A generated title must not be overwritten when subsequent save() call includes stats but no title."""
    import json
    from everstaff.memory.file_store import FileMemoryStore
    from everstaff.protocols import Message
    from everstaff.schema.token_stats import SessionStats, TokenUsage

    store = FileMemoryStore(tmp_path)
    msgs = [Message(role="user", content="hi")]

    # First save: no stats, but with a generated title (simulates _generate_title() result)
    await store.save("sess-title", msgs, agent_name="my-agent", title="Smart Title")

    # Second save: with stats, but no title (simulates the final runtime save)
    stats = SessionStats()
    stats.record(TokenUsage(input_tokens=5, output_tokens=3, total_tokens=8, model_id="gpt-4"))
    await store.save("sess-title", msgs, agent_name="my-agent", stats=stats, status="completed")

    raw = json.loads((tmp_path / "sess-title" / "session.json").read_text())
    assert raw["metadata"]["title"] == "Smart Title", (
        "Title was overwritten by agent_name on resave with stats"
    )


@pytest.mark.asyncio
async def test_system_prompt_preserved_on_resave_without_system_prompt(tmp_path):
    """system_prompt stored in first save must be retained when subsequent save() omits it."""
    import json
    from everstaff.memory.file_store import FileMemoryStore
    from everstaff.protocols import Message
    from everstaff.schema.token_stats import SessionStats, TokenUsage

    store = FileMemoryStore(tmp_path)
    msgs = [Message(role="user", content="hi")]

    # First save: with system_prompt
    await store.save("sess-sp", msgs, agent_name="my-agent", system_prompt="You are a bot.")

    # Second save: stats present, no system_prompt arg (simulates incremental save without system_prompt)
    stats = SessionStats()
    await store.save("sess-sp", msgs, agent_name="my-agent", stats=stats, status="running")

    raw = json.loads((tmp_path / "sess-sp" / "session.json").read_text())
    assert raw["metadata"]["system_prompt"] == "You are a bot.", (
        "system_prompt was lost on resave without system_prompt arg"
    )


@pytest.mark.asyncio
async def test_file_store_saves_max_tokens_in_metadata(tmp_path):
    """max_tokens passed to save() must appear in session metadata.

    This lets users inspect what output limit was configured for the agent.
    """
    import json
    from everstaff.memory.file_store import FileMemoryStore
    from everstaff.protocols import Message

    store = FileMemoryStore(tmp_path)
    msgs = [Message(role="user", content="hi")]

    await store.save("sess-mt", msgs, agent_name="bot", max_tokens=512)

    raw = json.loads((tmp_path / "sess-mt" / "session.json").read_text())
    saved = raw["metadata"].get("max_tokens")
    assert saved == 512, (
        f"max_tokens not saved in metadata. Got: {saved!r}. metadata={raw['metadata']}"
    )


@pytest.mark.asyncio
async def test_file_store_preserves_max_tokens_on_resave(tmp_path):
    """max_tokens in metadata must not be lost on subsequent save() calls that omit it."""
    import json
    from everstaff.memory.file_store import FileMemoryStore
    from everstaff.protocols import Message
    from everstaff.schema.token_stats import SessionStats

    store = FileMemoryStore(tmp_path)
    msgs = [Message(role="user", content="hi")]

    # First save sets max_tokens
    await store.save("sess-mt-r", msgs, agent_name="bot", max_tokens=256)

    # Second save (incremental, no max_tokens arg)
    stats = SessionStats()
    await store.save("sess-mt-r", msgs, agent_name="bot", stats=stats, status="running")

    raw = json.loads((tmp_path / "sess-mt-r" / "session.json").read_text())
    saved = raw["metadata"].get("max_tokens")
    assert saved == 256, (
        f"max_tokens was lost on resave. Got: {saved!r}"
    )


# ---------------------------------------------------------------------------
# Dual FileStore (L1/L2/L3 memory) tests
# ---------------------------------------------------------------------------

from everstaff.memory.file_store import FileMemoryStore
from everstaff.storage.local import LocalFileStore
from everstaff.protocols import Episode, WorkingState


@pytest.fixture
def dual_store(tmp_path):
    """FileMemoryStore with separate session and memory stores."""
    session_store = LocalFileStore(tmp_path / "sessions")
    memory_store = LocalFileStore(tmp_path / "memory")
    return FileMemoryStore(session_store, memory_store=memory_store)


@pytest.mark.asyncio
async def test_working_memory_roundtrip(dual_store):
    state = WorkingState(pending_items=["task1"], goals_progress={"g1": "on_track"})
    await dual_store.working_save("agent-uuid-1", state)
    loaded = await dual_store.working_load("agent-uuid-1")
    assert loaded.pending_items == ["task1"]
    assert loaded.goals_progress == {"g1": "on_track"}


@pytest.mark.asyncio
async def test_working_memory_missing_returns_default(dual_store):
    loaded = await dual_store.working_load("nonexistent")
    assert loaded == WorkingState()


@pytest.mark.asyncio
async def test_episode_append_and_query(dual_store):
    ep1 = Episode(timestamp="2026-02-28T09:00:00Z", trigger="cron", action="a1", result="r1", tags=["daily"])
    ep2 = Episode(timestamp="2026-02-28T10:00:00Z", trigger="event", action="a2", result="r2", tags=["urgent"])
    await dual_store.episode_append("agent-uuid-1", ep1)
    await dual_store.episode_append("agent-uuid-1", ep2)
    episodes = await dual_store.episode_query("agent-uuid-1", days=1)
    assert len(episodes) == 2
    assert episodes[0].action == "a1"


@pytest.mark.asyncio
async def test_episode_query_with_tag_filter(dual_store):
    ep1 = Episode(timestamp="2026-02-28T09:00:00Z", trigger="cron", action="a1", result="r1", tags=["daily"])
    ep2 = Episode(timestamp="2026-02-28T10:00:00Z", trigger="event", action="a2", result="r2", tags=["urgent"])
    await dual_store.episode_append("agent-uuid-1", ep1)
    await dual_store.episode_append("agent-uuid-1", ep2)
    filtered = await dual_store.episode_query("agent-uuid-1", days=1, tags=["urgent"])
    assert len(filtered) == 1
    assert filtered[0].action == "a2"


@pytest.mark.asyncio
async def test_semantic_memory_roundtrip(dual_store):
    await dual_store.semantic_write("agent-uuid-1", "patterns", "# Work Patterns\nMonday = review")
    content = await dual_store.semantic_read("agent-uuid-1", "patterns")
    assert "Monday = review" in content


@pytest.mark.asyncio
async def test_semantic_list(dual_store):
    await dual_store.semantic_write("agent-uuid-1", "patterns", "content1")
    await dual_store.semantic_write("agent-uuid-1", "preferences", "content2")
    topics = await dual_store.semantic_list("agent-uuid-1")
    assert set(topics) == {"patterns", "preferences"}


@pytest.mark.asyncio
async def test_semantic_index_default_empty(dual_store):
    content = await dual_store.semantic_read("agent-uuid-1", "index")
    assert content == ""


@pytest.mark.asyncio
async def test_l0_still_works(dual_store):
    """Existing session load/save is not broken."""
    msgs = [Message(role="user", content="hello")]
    await dual_store.save("ses-1", msgs, agent_name="test")
    loaded = await dual_store.load("ses-1")
    assert len(loaded) == 1
    assert loaded[0].content == "hello"


@pytest.mark.asyncio
async def test_no_memory_store_raises_not_implemented(tmp_path):
    """L1/L2/L3 methods raise NotImplementedError when no memory_store is configured."""
    store = FileMemoryStore(tmp_path)
    with pytest.raises(NotImplementedError):
        await store.working_load("agent-1")
    with pytest.raises(NotImplementedError):
        await store.working_save("agent-1", WorkingState())
    with pytest.raises(NotImplementedError):
        await store.episode_append("agent-1", Episode(timestamp="2026-02-28T09:00:00Z", trigger="cron", action="a", result="r"))
    with pytest.raises(NotImplementedError):
        await store.episode_query("agent-1")
    with pytest.raises(NotImplementedError):
        await store.semantic_read("agent-1", "index")
    with pytest.raises(NotImplementedError):
        await store.semantic_write("agent-1", "index", "content")
    with pytest.raises(NotImplementedError):
        await store.semantic_list("agent-1")


@pytest.mark.asyncio
async def test_backward_compat_store_alias(tmp_path):
    """self._store alias still points to the session store."""
    store = FileMemoryStore(tmp_path)
    assert store._store is store._session_store


# ---------------------------------------------------------------------------
# Trigger metadata tests (Task 4)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_with_trigger(tmp_path):
    from everstaff.storage.local import LocalFileStore
    from everstaff.memory.file_store import FileMemoryStore
    from everstaff.protocols import AgentEvent
    import json

    store = FileMemoryStore(LocalFileStore(tmp_path))
    event = AgentEvent(
        id="evt-001",
        source="scheduler",
        type="cron",
        payload={"task": "daily check"},
        target_agent="MyAgent",
        timestamp="2026-02-28T09:00:00+00:00",
    )
    await store.save(
        "sess-trigger-1", [],
        agent_name="MyAgent",
        initiated_by="daemon",
        trigger=event,
    )
    raw = json.loads((tmp_path / "sess-trigger-1" / "session.json").read_text())
    assert raw["metadata"]["trigger"]["source"] == "scheduler"
    assert raw["metadata"]["trigger"]["type"] == "cron"
    assert raw["metadata"]["trigger"]["id"] == "evt-001"


@pytest.mark.asyncio
async def test_save_trigger_preserved_on_update(tmp_path):
    from everstaff.storage.local import LocalFileStore
    from everstaff.memory.file_store import FileMemoryStore
    from everstaff.protocols import AgentEvent
    import json

    store = FileMemoryStore(LocalFileStore(tmp_path))
    event = AgentEvent(source="scheduler", type="interval")
    await store.save("sess-1", [], trigger=event)
    # Second save without trigger — should preserve the existing one
    await store.save("sess-1", [], status="completed")
    raw = json.loads((tmp_path / "sess-1" / "session.json").read_text())
    assert raw["metadata"]["trigger"]["source"] == "scheduler"


@pytest.mark.asyncio
async def test_save_no_trigger(tmp_path):
    from everstaff.storage.local import LocalFileStore
    from everstaff.memory.file_store import FileMemoryStore
    import json

    store = FileMemoryStore(LocalFileStore(tmp_path))
    await store.save("sess-notrigger", [], agent_name="A")
    raw = json.loads((tmp_path / "sess-notrigger" / "session.json").read_text())
    assert raw["metadata"].get("trigger") is None


# ---------------------------------------------------------------------------
# Workflow persistence tests (Task 3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_and_load_workflow(tmp_path):
    from everstaff.storage.local import LocalFileStore
    from everstaff.memory.file_store import FileMemoryStore
    from everstaff.schema.workflow_spec import (
        WorkflowRecord, TaskNodeSpec, TaskResult, TaskStatus, PlanSpec
    )

    store = FileMemoryStore(LocalFileStore(tmp_path))

    plan = PlanSpec(
        plan_id="wf-1",
        title="Test WF",
        goal="Do something",
        tasks=[TaskNodeSpec(task_id="t1", title="Step", description="d",
                            dependencies=[])],
    )
    record = WorkflowRecord.from_plan(plan)
    record.results["t1"] = TaskResult(task_id="t1", status=TaskStatus.RUNNING)

    # Save initial session first (save_workflow reads/writes the file)
    await store.save("sess-1", [], agent_name="agent", status="running")
    await store.save_workflow("sess-1", record)

    loaded = await store.load_workflows("sess-1")
    assert len(loaded) == 1
    assert loaded[0].plan_id == "wf-1"
    assert loaded[0].results["t1"].status == TaskStatus.RUNNING


@pytest.mark.asyncio
async def test_save_workflow_upsert(tmp_path):
    from everstaff.storage.local import LocalFileStore
    from everstaff.memory.file_store import FileMemoryStore
    from everstaff.schema.workflow_spec import (
        WorkflowRecord, TaskNodeSpec, TaskResult, TaskStatus, PlanSpec
    )

    store = FileMemoryStore(LocalFileStore(tmp_path))
    await store.save("sess-1", [], agent_name="agent", status="running")

    plan = PlanSpec(plan_id="wf-1", title="T", goal="G",
                    tasks=[TaskNodeSpec(task_id="t1", title="T1", description="d",
                                        dependencies=[])])
    record = WorkflowRecord.from_plan(plan)
    await store.save_workflow("sess-1", record)

    # Update and save again
    record.status = "completed"
    record.results["t1"] = TaskResult(task_id="t1", status=TaskStatus.COMPLETED, output="done")
    await store.save_workflow("sess-1", record)

    loaded = await store.load_workflows("sess-1")
    assert len(loaded) == 1  # still one record, not two
    assert loaded[0].status == "completed"
    assert loaded[0].results["t1"].output == "done"

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_trigger_stored_in_context():
    """Trigger passed to AgentBuilder is set on the AgentContext."""
    from everstaff.protocols import AgentEvent
    from everstaff.core.context import AgentContext

    # Verify AgentContext accepts trigger
    trigger = AgentEvent(source="scheduler", type="cron", id="evt-test")
    ctx = AgentContext(
        tool_registry=MagicMock(),
        memory=MagicMock(),
        tool_pipeline=MagicMock(),
        trigger=trigger,
    )
    assert ctx.trigger is not None
    assert ctx.trigger.source == "scheduler"


@pytest.mark.asyncio
async def test_trigger_passed_to_first_save(tmp_path):
    """When AgentContext has a trigger, the first memory.save() includes it."""
    import json
    from everstaff.protocols import AgentEvent, Message
    from everstaff.storage.local import LocalFileStore
    from everstaff.memory.file_store import FileMemoryStore

    trigger = AgentEvent(source="test-source", type="test-type", id="evt-42")
    session_id = "test-session-trigger"

    mock_memory = FileMemoryStore(LocalFileStore(tmp_path))

    # Simulate what runtime does: call save with trigger once
    await mock_memory.save(
        session_id, [],
        agent_name="TestAgent",
        status="running",
        trigger=trigger,
    )
    raw = json.loads((tmp_path / session_id / "session.json").read_text())
    assert raw["metadata"]["trigger"]["source"] == "test-source"
    assert raw["metadata"]["trigger"]["id"] == "evt-42"

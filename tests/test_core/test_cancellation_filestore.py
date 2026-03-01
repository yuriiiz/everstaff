"""Tests for FileStore-based cancellation signal."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from everstaff.storage.local import LocalFileStore
from everstaff.protocols import LLMResponse


def _make_runtime_with_store(tmp_path, llm, file_store):
    """Build a minimal AgentRuntime wired to a real LocalFileStore."""
    from everstaff.core.context import AgentContext
    from everstaff.core.runtime import AgentRuntime
    from everstaff.tools.pipeline import ToolCallPipeline
    from everstaff.tools.stages import ExecutionStage
    from everstaff.tools.default_registry import DefaultToolRegistry
    from everstaff.nulls import NullTracer
    from everstaff.memory.file_store import FileMemoryStore

    reg = DefaultToolRegistry()
    pipeline = ToolCallPipeline([ExecutionStage(reg)])
    memory = FileMemoryStore(tmp_path)
    ctx = AgentContext(
        tool_registry=reg,
        memory=memory,
        tool_pipeline=pipeline,
        tracer=NullTracer(),
        agent_name="test-agent",
        file_store=file_store,
    )
    return AgentRuntime(context=ctx, llm_client=llm), ctx


@pytest.mark.asyncio
async def test_cancel_signal_file_stops_session(tmp_path):
    """Writing cancel.signal to FileStore should stop the session."""
    store = LocalFileStore(str(tmp_path))
    llm = MagicMock()
    llm.complete_stream = None  # prevent AsyncMock auto-attribute from triggering streaming path
    llm.complete = AsyncMock(return_value=LLMResponse(content="done", tool_calls=[]))

    runtime, ctx = _make_runtime_with_store(tmp_path, llm, store)

    # Write cancel signal before run — session should stop immediately
    await store.write(f"{ctx.session_id}/cancel.signal", b"1")

    from everstaff.schema.stream import SessionEnd
    events = []
    async for ev in runtime.run_stream("hello"):
        events.append(ev)

    session_ends = [e for e in events if isinstance(e, SessionEnd)]
    assert session_ends, "Expected a SessionEnd event"
    assert session_ends[0].response == "[Stopped]"


@pytest.mark.asyncio
async def test_no_cancel_signal_runs_normally(tmp_path):
    """Without cancel.signal, session runs to completion."""
    store = LocalFileStore(str(tmp_path))
    llm = MagicMock()
    llm.complete_stream = None  # prevent AsyncMock auto-attribute from triggering streaming path
    llm.complete = AsyncMock(return_value=LLMResponse(content="hello!", tool_calls=[]))

    runtime, ctx = _make_runtime_with_store(tmp_path, llm, store)

    from everstaff.schema.stream import SessionEnd
    events = []
    async for ev in runtime.run_stream("hi"):
        events.append(ev)

    session_ends = [e for e in events if isinstance(e, SessionEnd)]
    assert session_ends[0].response == "hello!"


@pytest.mark.asyncio
async def test_cancel_signal_deleted_on_completion(tmp_path):
    """cancel.signal file must be deleted when session ends normally."""
    store = LocalFileStore(str(tmp_path))
    llm = MagicMock()
    llm.complete_stream = None  # prevent AsyncMock auto-attribute from triggering streaming path
    llm.complete = AsyncMock(return_value=LLMResponse(content="done", tool_calls=[]))

    runtime, ctx = _make_runtime_with_store(tmp_path, llm, store)
    signal_path = f"{ctx.session_id}/cancel.signal"

    async for _ in runtime.run_stream("hi"):
        pass

    # After normal completion, no cancel.signal should exist
    assert not await store.exists(signal_path)

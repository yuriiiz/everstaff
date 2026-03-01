import pytest
from unittest.mock import AsyncMock, MagicMock


def _make_ctx(memory=None, cancellation=None, tracer=None):
    """Helper to build a minimal AgentContext."""
    from everstaff.core.context import AgentContext
    from everstaff.protocols import CancellationEvent
    from everstaff.nulls import NullTracer, AllowAllChecker
    from everstaff.tools.pipeline import ToolCallPipeline
    from everstaff.tools.stages import ExecutionStage, PermissionStage
    from everstaff.tools.default_registry import DefaultToolRegistry

    if memory is None:
        memory = AsyncMock()
        memory.load = AsyncMock(return_value=[])
        memory.save = AsyncMock()

    registry = DefaultToolRegistry()
    pipeline = ToolCallPipeline([PermissionStage(AllowAllChecker()), ExecutionStage(registry)])
    return AgentContext(
        tool_registry=registry,
        memory=memory,
        tool_pipeline=pipeline,
        agent_name="test",
        tracer=tracer or NullTracer(),
        cancellation=cancellation or CancellationEvent(),
    )


@pytest.mark.asyncio
async def test_run_stream_emits_thinking_delta():
    """When LLM returns thinking, run_stream() yields ThinkingDelta before TextDelta."""
    from everstaff.core.runtime import AgentRuntime
    from everstaff.protocols import LLMResponse
    from everstaff.schema.stream import ThinkingDelta, TextDelta, SessionEnd

    ctx = _make_ctx()
    llm = AsyncMock()
    llm.complete_stream = None  # prevent AsyncMock auto-attribute from triggering streaming path
    llm.complete = AsyncMock(return_value=LLMResponse(
        content="The answer is 42",
        tool_calls=[],
        thinking="Let me think about this carefully...",
    ))

    runtime = AgentRuntime(context=ctx, llm_client=llm)
    events = []
    async for event in runtime.run_stream("What is 6*7?"):
        events.append(event)

    event_types = [type(e).__name__ for e in events]
    assert "ThinkingDelta" in event_types
    thinking_event = next(e for e in events if isinstance(e, ThinkingDelta))
    assert thinking_event.content == "Let me think about this carefully..."
    # ThinkingDelta must come before TextDelta
    assert event_types.index("ThinkingDelta") < event_types.index("TextDelta")


@pytest.mark.asyncio
async def test_no_thinking_delta_when_thinking_absent():
    """When LLM returns no thinking, no ThinkingDelta is emitted."""
    from everstaff.core.runtime import AgentRuntime
    from everstaff.protocols import LLMResponse
    from everstaff.schema.stream import ThinkingDelta

    ctx = _make_ctx()
    llm = AsyncMock()
    llm.complete_stream = None  # prevent AsyncMock auto-attribute from triggering streaming path
    llm.complete = AsyncMock(return_value=LLMResponse(
        content="Hello",
        tool_calls=[],
        thinking=None,
    ))

    runtime = AgentRuntime(context=ctx, llm_client=llm)
    events = []
    async for event in runtime.run_stream("Hi"):
        events.append(event)

    assert not any(isinstance(e, ThinkingDelta) for e in events)


@pytest.mark.asyncio
async def test_thinking_stored_and_stripped_for_llm():
    """Thinking is stored in session but stripped before being sent to LLM."""
    from everstaff.core.runtime import AgentRuntime
    from everstaff.protocols import LLMResponse, Message
    import json, tempfile, pathlib

    tmp = pathlib.Path(tempfile.mkdtemp())
    from everstaff.memory.file_store import FileMemoryStore
    memory = FileMemoryStore(tmp)

    call_count = 0
    messages_sent_to_llm = []

    async def fake_complete(messages, tools, system=None):
        nonlocal call_count
        call_count += 1
        messages_sent_to_llm.extend(messages)
        # First call: return thinking + content
        if call_count == 1:
            return LLMResponse(
                content="First response",
                tool_calls=[],
                thinking="My internal reasoning",
            )
        # Second call (resume): should not have thinking in messages
        return LLMResponse(content="Second response", tool_calls=[])

    ctx = _make_ctx(memory=memory)
    llm = MagicMock()
    llm.complete_stream = None  # prevent MagicMock auto-attribute from triggering streaming path
    llm.complete = fake_complete

    from everstaff.core.runtime import AgentRuntime
    runtime = AgentRuntime(context=ctx, llm_client=llm)

    # First run — should store thinking
    async for _ in runtime.run_stream("First question"):
        pass

    # Verify thinking stored in session.json
    session_file = tmp / ctx.session_id / "session.json"
    raw = json.loads(session_file.read_text())
    assistant_msgs = [m for m in raw["messages"] if m["role"] == "assistant"]
    assert len(assistant_msgs) == 1
    assert assistant_msgs[0].get("thinking") == "My internal reasoning"

    # Verify thinking NOT in messages sent to LLM
    llm_assistant_msgs = [m for m in messages_sent_to_llm if m.role == "assistant"]
    for m in llm_assistant_msgs:
        assert m.thinking is None, f"thinking should be stripped but got: {m.thinking}"

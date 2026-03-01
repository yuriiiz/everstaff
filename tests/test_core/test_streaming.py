import pytest
from unittest.mock import AsyncMock
from everstaff.protocols import LLMResponse, ToolCallRequest, ToolDefinition, ToolResult
from everstaff.schema.stream import TextDelta, ToolCallStart, ToolCallEnd, TurnStart, SessionEnd, ErrorEvent
from everstaff.core.runtime import AgentRuntime
from everstaff.core.context import AgentContext
from everstaff.nulls import NullTracer, AllowAllChecker
from everstaff.tools.pipeline import ToolCallPipeline
from everstaff.tools.stages import ExecutionStage, PermissionStage
from everstaff.tools.default_registry import DefaultToolRegistry


def _make_runtime(llm_responses):
    registry = DefaultToolRegistry()
    pipeline = ToolCallPipeline([PermissionStage(AllowAllChecker()), ExecutionStage(registry)])
    memory = AsyncMock()
    memory.load = AsyncMock(return_value=[])
    memory.save = AsyncMock()
    llm = AsyncMock()
    llm.complete = AsyncMock(side_effect=llm_responses)
    llm.complete_stream = None  # ensure fallback to complete() path
    ctx = AgentContext(
        tool_registry=registry,
        memory=memory,
        tool_pipeline=pipeline,
        agent_name="streamer",
        session_id="sess-stream",
        tracer=NullTracer(),
    )
    return AgentRuntime(context=ctx, llm_client=llm)


@pytest.mark.asyncio
async def test_run_stream_emits_turn_start_and_session_end():
    """Basic stream: TurnStart then TextDelta(s) then SessionEnd."""
    runtime = _make_runtime([LLMResponse(content="Hello world", tool_calls=[])])
    events = [e async for e in runtime.run_stream("Hi")]
    kinds = [type(e).__name__ for e in events]
    assert "TurnStart" in kinds
    assert "SessionEnd" in kinds
    session_end = next(e for e in events if isinstance(e, SessionEnd))
    assert session_end.response == "Hello world"


@pytest.mark.asyncio
async def test_run_stream_emits_text_deltas():
    """TextDelta events should compose into the final response."""
    runtime = _make_runtime([LLMResponse(content="Streamed reply", tool_calls=[])])
    deltas = [e.content async for e in runtime.run_stream("Hi") if isinstance(e, TextDelta)]
    assert "".join(deltas) == "Streamed reply"


@pytest.mark.asyncio
async def test_run_stream_emits_tool_events():
    """Tool calls produce ToolCallStart then ToolCallEnd events."""
    class EchoTool:
        @property
        def definition(self):
            return ToolDefinition(name="echo", description="echoes", parameters={
                "type": "object", "properties": {"msg": {"type": "string"}}, "required": ["msg"]
            })
        async def execute(self, args):
            return ToolResult(tool_call_id="", content=args["msg"])

    registry = DefaultToolRegistry()
    registry.register(EchoTool())
    pipeline = ToolCallPipeline([PermissionStage(AllowAllChecker()), ExecutionStage(registry)])
    memory = AsyncMock()
    memory.load = AsyncMock(return_value=[])
    memory.save = AsyncMock()
    llm = AsyncMock()
    llm.complete = AsyncMock(side_effect=[
        LLMResponse(content=None, tool_calls=[ToolCallRequest(id="tc1", name="echo", args={"msg": "ping"})]),
        LLMResponse(content="Done", tool_calls=[]),
    ])
    llm.complete_stream = None  # ensure fallback to complete() path
    ctx = AgentContext(
        tool_registry=registry, memory=memory, tool_pipeline=pipeline,
        agent_name="test", session_id="sess-tools", tracer=NullTracer(),
    )
    runtime = AgentRuntime(context=ctx, llm_client=llm)
    events = [e async for e in runtime.run_stream("call echo")]
    assert any(isinstance(e, ToolCallStart) and e.name == "echo" for e in events)
    assert any(isinstance(e, ToolCallEnd) and e.name == "echo" for e in events)


@pytest.mark.asyncio
async def test_run_is_wrapper_around_run_stream():
    """run() must return the same final response as run_stream() SessionEnd."""
    runtime = _make_runtime([LLMResponse(content="Final answer", tool_calls=[])])
    result = await runtime.run("question")
    assert result == "Final answer"


@pytest.mark.asyncio
async def test_run_stream_uses_complete_stream_when_available():
    """When LLM has complete_stream(), runtime yields TextDeltas as chunks arrive (not one block)."""
    from everstaff.schema.stream import SessionEnd

    registry = DefaultToolRegistry()
    pipeline = ToolCallPipeline([PermissionStage(AllowAllChecker()), ExecutionStage(registry)])
    memory = AsyncMock()
    memory.load = AsyncMock(return_value=[])
    memory.save = AsyncMock()

    async def fake_complete_stream(messages, tools, system=None):
        yield ("text", "Hello ")
        yield ("text", "world")
        yield ("done", LLMResponse(content="Hello world", tool_calls=[]))

    llm = AsyncMock()
    llm.complete_stream = fake_complete_stream
    llm.complete = AsyncMock(side_effect=Exception("complete() should not be called"))

    ctx = AgentContext(
        tool_registry=registry,
        memory=memory,
        tool_pipeline=pipeline,
        agent_name="streamer",
        session_id="sess-cs",
        tracer=NullTracer(),
    )
    runtime = AgentRuntime(context=ctx, llm_client=llm)
    events = [e async for e in runtime.run_stream("Hi")]

    text_deltas = [e for e in events if isinstance(e, TextDelta)]
    assert len(text_deltas) == 2, f"Expected 2 TextDeltas (one per chunk), got {len(text_deltas)}: {text_deltas}"
    assert text_deltas[0].content == "Hello "
    assert text_deltas[1].content == "world"

    session_end = next(e for e in events if isinstance(e, SessionEnd))
    assert session_end.response == "Hello world"

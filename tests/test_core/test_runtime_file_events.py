import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from everstaff.protocols import LLMResponse, ToolCallRequest, ToolDefinition, ToolResult, Message


class WriteFileTool:
    """Test tool that writes a file to workdir."""
    def __init__(self, workdir: Path):
        self._workdir = workdir

    @property
    def definition(self):
        return ToolDefinition("Write", "Write file", {})

    async def execute(self, args):
        path = self._workdir / args.get("file_path", "test.txt")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(args.get("content", "hello"))
        return ToolResult(tool_call_id="", content=f"Wrote {path.name}")


def _make_ctx_with_workdir(tmp_path):
    from everstaff.core.context import AgentContext
    from everstaff.tools.default_registry import DefaultToolRegistry
    from everstaff.tools.pipeline import ToolCallPipeline
    from everstaff.tools.stages import ExecutionStage
    from everstaff.nulls import InMemoryStore, NullTracer

    reg = DefaultToolRegistry()
    tool = WriteFileTool(tmp_path)
    reg.register(tool)
    pipeline = ToolCallPipeline([ExecutionStage(reg)])
    return AgentContext(
        tool_registry=reg,
        memory=InMemoryStore(),
        tool_pipeline=pipeline,
        tracer=NullTracer(),
        agent_name="test-agent",
        workdir=tmp_path,
    )


@pytest.mark.asyncio
async def test_runtime_emits_file_created_event(tmp_path):
    from everstaff.core.runtime import AgentRuntime
    from everstaff.schema.stream import FileCreatedEvent, ToolCallEnd

    ctx = _make_ctx_with_workdir(tmp_path)

    tc = ToolCallRequest(id="tc1", name="Write", args={"file_path": "result.md", "content": "# Hello"})
    llm = MagicMock()
    llm.complete_stream = None
    llm.complete = AsyncMock(side_effect=[
        LLMResponse(content="", tool_calls=[tc]),
        LLMResponse(content="Done!", tool_calls=[]),
    ])

    runtime = AgentRuntime(context=ctx, llm_client=llm)
    events = []
    async for event in runtime.run_stream("write a file"):
        events.append(event)

    file_events = [e for e in events if isinstance(e, FileCreatedEvent)]
    assert len(file_events) == 1
    assert file_events[0].file_name == "result.md"
    assert file_events[0].file_path == "result.md"
    assert file_events[0].mime_type == "text/markdown"
    assert file_events[0].size > 0


@pytest.mark.asyncio
async def test_runtime_no_file_event_when_no_files_created(tmp_path):
    from everstaff.core.runtime import AgentRuntime
    from everstaff.schema.stream import FileCreatedEvent

    from everstaff.core.context import AgentContext
    from everstaff.tools.default_registry import DefaultToolRegistry
    from everstaff.tools.pipeline import ToolCallPipeline
    from everstaff.tools.stages import ExecutionStage
    from everstaff.nulls import InMemoryStore, NullTracer

    class NoopTool:
        @property
        def definition(self):
            return ToolDefinition("noop", "noop", {})
        async def execute(self, args):
            return ToolResult(tool_call_id="", content="ok")

    reg = DefaultToolRegistry()
    reg.register(NoopTool())
    pipeline = ToolCallPipeline([ExecutionStage(reg)])
    ctx = AgentContext(
        tool_registry=reg, memory=InMemoryStore(), tool_pipeline=pipeline,
        tracer=NullTracer(), agent_name="test", workdir=tmp_path,
    )

    tc = ToolCallRequest(id="tc1", name="noop", args={})
    llm = MagicMock()
    llm.complete_stream = None
    llm.complete = AsyncMock(side_effect=[
        LLMResponse(content="", tool_calls=[tc]),
        LLMResponse(content="Done!", tool_calls=[]),
    ])

    runtime = AgentRuntime(context=ctx, llm_client=llm)
    events = []
    async for event in runtime.run_stream("do nothing"):
        events.append(event)

    file_events = [e for e in events if isinstance(e, FileCreatedEvent)]
    assert len(file_events) == 0

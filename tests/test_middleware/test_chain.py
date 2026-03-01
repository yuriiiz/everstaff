import pytest
from everstaff.protocols import ToolResult


@pytest.fixture
def fake_context(tmp_path):
    from everstaff.tools.default_registry import DefaultToolRegistry
    from everstaff.nulls import InMemoryStore, NullTracer, AllowAllChecker
    from everstaff.tools.pipeline import ToolCallPipeline
    from everstaff.tools.stages import ExecutionStage
    from everstaff.core.context import AgentContext

    reg = DefaultToolRegistry()
    pipeline = ToolCallPipeline([ExecutionStage(reg)])
    return AgentContext(
        tool_registry=reg,
        memory=InMemoryStore(),
        tool_pipeline=pipeline,
    )


@pytest.mark.asyncio
async def test_tool_call_pipeline_calls_execution():
    from everstaff.tools.default_registry import DefaultToolRegistry
    from everstaff.nulls import InMemoryStore
    from everstaff.tools.pipeline import ToolCallPipeline, ToolCallContext
    from everstaff.tools.stages import ExecutionStage
    from everstaff.core.context import AgentContext
    from everstaff.protocols import ToolDefinition, ToolResult

    class EchoTool:
        @property
        def definition(self):
            return ToolDefinition("echo", "echoes input", {"type": "object", "properties": {"msg": {"type": "string"}}})
        async def execute(self, args):
            return ToolResult(tool_call_id="", content=args["msg"])

    reg = DefaultToolRegistry()
    reg.register(EchoTool())
    pipeline = ToolCallPipeline([ExecutionStage(reg)])
    ctx = AgentContext(tool_registry=reg, memory=InMemoryStore(), tool_pipeline=pipeline)

    tcc = ToolCallContext(tool_name="echo", args={"msg": "hello"}, agent_context=ctx, tool_call_id="c1")
    result = await pipeline.execute(tcc)
    assert result.content == "hello"


@pytest.mark.asyncio
async def test_pipeline_order_is_preserved():
    from everstaff.tools.default_registry import DefaultToolRegistry
    from everstaff.nulls import InMemoryStore
    from everstaff.tools.pipeline import ToolCallPipeline, ToolCallContext
    from everstaff.tools.stages import ExecutionStage
    from everstaff.core.context import AgentContext
    from everstaff.protocols import ToolDefinition, ToolResult
    from typing import Callable, Awaitable

    calls: list[str] = []

    class RecordStage:
        def __init__(self, name: str):
            self._name = name
        async def __call__(self, ctx: ToolCallContext, next: Callable) -> ToolResult:
            calls.append(f"before:{self._name}")
            result = await next(ctx)
            calls.append(f"after:{self._name}")
            return result

    class NoopTool:
        @property
        def definition(self):
            return ToolDefinition("noop", "does nothing", {"type": "object", "properties": {}})
        async def execute(self, args):
            return ToolResult(tool_call_id="", content="done")

    reg = DefaultToolRegistry()
    reg.register(NoopTool())
    pipeline = ToolCallPipeline([
        RecordStage("A"),
        RecordStage("B"),
        ExecutionStage(reg),
    ])
    ctx = AgentContext(tool_registry=reg, memory=InMemoryStore(), tool_pipeline=pipeline)
    tcc = ToolCallContext(tool_name="noop", args={}, agent_context=ctx, tool_call_id="c1")
    await pipeline.execute(tcc)

    assert calls == ["before:A", "before:B", "after:B", "after:A"]


@pytest.mark.asyncio
async def test_permission_stage_blocks():
    from everstaff.tools.default_registry import DefaultToolRegistry
    from everstaff.nulls import InMemoryStore, DenyAllChecker
    from everstaff.tools.pipeline import ToolCallPipeline, ToolCallContext
    from everstaff.tools.stages import ExecutionStage, PermissionStage
    from everstaff.core.context import AgentContext
    from everstaff.protocols import ToolDefinition, ToolResult

    class NoopTool:
        @property
        def definition(self):
            return ToolDefinition("noop", "does nothing", {"type": "object", "properties": {}})
        async def execute(self, args):
            return ToolResult(tool_call_id="", content="done")

    reg = DefaultToolRegistry()
    reg.register(NoopTool())
    checker = DenyAllChecker()
    pipeline = ToolCallPipeline([
        PermissionStage(checker),
        ExecutionStage(reg),
    ])
    ctx = AgentContext(tool_registry=reg, memory=InMemoryStore(), tool_pipeline=pipeline)
    tcc = ToolCallContext(tool_name="noop", args={}, agent_context=ctx, tool_call_id="c1")
    result = await pipeline.execute(tcc)
    assert result.is_error
    assert "deny-all" in result.content

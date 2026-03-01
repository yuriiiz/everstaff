import pytest
from unittest.mock import MagicMock, AsyncMock
from everstaff.protocols import LLMResponse, Message


@pytest.mark.asyncio
async def test_hook_on_user_input_can_mutate():
    """on_user_input hook can transform user input."""
    from everstaff.hooks.base import BaseHook
    from everstaff.core.runtime import AgentRuntime

    class UppercaseHook(BaseHook):
        async def on_user_input(self, ctx, content):
            return content.upper()

    ctx = _make_ctx(hooks=[UppercaseHook()])
    received_msgs = []
    llm = MagicMock()
    llm.complete_stream = None  # prevent MagicMock auto-attribute from triggering streaming path
    async def capture(messages, tools, system=None):
        received_msgs.extend(messages)
        return LLMResponse(content="ok", tool_calls=[])
    llm.complete = AsyncMock(side_effect=capture)

    runtime = AgentRuntime(ctx, llm)
    await runtime.run("hello")
    assert any(m.content == "HELLO" for m in received_msgs if m.role == "user")


@pytest.mark.asyncio
async def test_hook_exception_does_not_crash_runtime():
    """Hook that raises must not propagate to main flow."""
    from everstaff.hooks.base import BaseHook
    from everstaff.core.runtime import AgentRuntime

    class BrokenHook(BaseHook):
        async def on_user_input(self, ctx, content):
            raise RuntimeError("broken hook!")

    ctx = _make_ctx(hooks=[BrokenHook()])
    llm = MagicMock()
    llm.complete_stream = None  # prevent MagicMock auto-attribute from triggering streaming path
    llm.complete = AsyncMock(return_value=LLMResponse(content="ok", tool_calls=[]))
    runtime = AgentRuntime(ctx, llm)
    result = await runtime.run("hello")   # must not raise
    assert result == "ok"


@pytest.mark.asyncio
async def test_hook_on_session_start_called():
    from everstaff.hooks.base import BaseHook
    from everstaff.core.runtime import AgentRuntime
    calls = []

    class TrackHook(BaseHook):
        async def on_session_start(self, ctx):
            calls.append("started")

    ctx = _make_ctx(hooks=[TrackHook()])
    llm = MagicMock()
    llm.complete_stream = None  # prevent MagicMock auto-attribute from triggering streaming path
    llm.complete = AsyncMock(return_value=LLMResponse(content="ok", tool_calls=[]))
    runtime = AgentRuntime(ctx, llm)
    await runtime.run("hi")
    assert calls == ["started"]


def _make_ctx(hooks=None):
    from everstaff.core.context import AgentContext
    from everstaff.tools.pipeline import ToolCallPipeline
    from everstaff.tools.stages import ExecutionStage
    from everstaff.tools.default_registry import DefaultToolRegistry
    from everstaff.nulls import InMemoryStore, NullTracer
    reg = DefaultToolRegistry()
    pipeline = ToolCallPipeline([ExecutionStage(reg)])
    return AgentContext(
        tool_registry=reg,
        memory=InMemoryStore(),
        tool_pipeline=pipeline,
        tracer=NullTracer(),
        hooks=hooks or [],
        agent_name="test",
    )

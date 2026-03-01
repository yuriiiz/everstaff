"""Tests for HITL exception bubbling through runtime."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from everstaff.protocols import (
    HitlRequest, HumanApprovalRequired, LLMResponse,
    ToolCallRequest, ToolDefinition, ToolResult, Message,
)


class HitlTool:
    """Fake tool that raises HumanApprovalRequired."""
    @property
    def definition(self):
        return ToolDefinition("ask_human", "ask", {"type": "object", "properties": {}})

    async def execute(self, args):
        req = HitlRequest(hitl_id="h-test", type="provide_input", prompt="Question?")
        raise HumanApprovalRequired([req])


def _make_ctx_with_hitl_tool(memory=None):
    from everstaff.core.context import AgentContext
    from everstaff.tools.default_registry import DefaultToolRegistry
    from everstaff.tools.pipeline import ToolCallPipeline
    from everstaff.tools.stages import ExecutionStage
    from everstaff.nulls import InMemoryStore, NullTracer

    reg = DefaultToolRegistry()
    reg.register(HitlTool())
    pipeline = ToolCallPipeline([ExecutionStage(reg)])
    return AgentContext(
        tool_registry=reg,
        memory=memory or InMemoryStore(),
        tool_pipeline=pipeline,
        tracer=NullTracer(),
        agent_name="test-agent",
    )


@pytest.mark.asyncio
async def test_runtime_run_reraies_human_approval_required():
    """runtime.run() must re-raise HumanApprovalRequired, not swallow it."""
    from everstaff.core.runtime import AgentRuntime

    llm = MagicMock()
    llm.complete_stream = None  # prevent AsyncMock auto-attribute from triggering streaming path
    llm.complete = AsyncMock(return_value=LLMResponse(
        content=None,
        tool_calls=[ToolCallRequest(id="c1", name="ask_human", args={})],
    ))

    ctx = _make_ctx_with_hitl_tool()
    runtime = AgentRuntime(context=ctx, llm_client=llm)

    with pytest.raises(HumanApprovalRequired) as exc_info:
        await runtime.run("test")

    assert len(exc_info.value.requests) == 1
    assert exc_info.value.requests[0].hitl_id == "h-test"


@pytest.mark.asyncio
async def test_runtime_checkpoints_session_on_hitl():
    """runtime must save session with status=waiting_for_human before re-raising."""
    from everstaff.core.runtime import AgentRuntime
    from everstaff.nulls import InMemoryStore

    mem = InMemoryStore()
    llm = MagicMock()
    llm.complete_stream = None  # prevent AsyncMock auto-attribute from triggering streaming path
    llm.complete = AsyncMock(return_value=LLMResponse(
        content=None,
        tool_calls=[ToolCallRequest(id="c1", name="ask_human", args={})],
    ))

    ctx = _make_ctx_with_hitl_tool(memory=mem)
    runtime = AgentRuntime(context=ctx, llm_client=llm)

    with pytest.raises(HumanApprovalRequired):
        await runtime.run("test")

    # Session should be saved with waiting_for_human status
    # InMemoryStore stores raw — check via internal state
    assert ctx.session_id in mem._sessions


@pytest.mark.asyncio
async def test_runtime_annotates_tool_call_id_on_hitl_requests():
    """Each HITL request must have tool_call_id set to the triggering tool call."""
    from everstaff.core.runtime import AgentRuntime

    llm = MagicMock()
    llm.complete_stream = None  # prevent AsyncMock auto-attribute from triggering streaming path
    llm.complete = AsyncMock(return_value=LLMResponse(
        content=None,
        tool_calls=[ToolCallRequest(id="call-abc", name="ask_human", args={})],
    ))

    ctx = _make_ctx_with_hitl_tool()
    runtime = AgentRuntime(context=ctx, llm_client=llm)

    with pytest.raises(HumanApprovalRequired) as exc_info:
        await runtime.run("test")

    assert exc_info.value.requests[0].tool_call_id == "call-abc"

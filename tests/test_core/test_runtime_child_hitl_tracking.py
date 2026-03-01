"""Runtime must track unresolved child HITL requests and raise at session end."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from everstaff.protocols import (
    HitlRequest, HumanApprovalRequired, LLMResponse,
    ToolCallRequest, ToolDefinition, ToolResult, Message,
)


class ChildHitlTool:
    """Fake tool that returns a ToolResult with child HITL metadata."""
    @property
    def definition(self):
        return ToolDefinition("delegate_task_to_subagent", "delegate", {
            "type": "object",
            "properties": {
                "agent_name": {"type": "string"},
                "prompt": {"type": "string"},
                "resume_session_id": {"type": "string"},
                "hitl_response": {"type": "object"},
            },
            "required": ["agent_name", "prompt"],
        })

    def __init__(self):
        self.call_count = 0

    async def execute(self, args):
        self.call_count += 1
        if args.get("resume_session_id"):
            # Resume call — child completes successfully
            return ToolResult(tool_call_id="", content="Child completed successfully")
        # Initial call — child HITL escalation
        content = "[SUB_AGENT_HITL]\nagent_name: child\nchild_session_id: child-sess\nhitl_request_count: 1"
        result = ToolResult(tool_call_id="", content=content)
        result._child_hitl_requests = [
            HitlRequest(hitl_id="child-h1", type="approve_reject", prompt="OK?",
                        origin_session_id="child-sess", origin_agent_name="child")
        ]
        return result


def _make_ctx(tool=None, memory=None):
    from everstaff.core.context import AgentContext
    from everstaff.tools.default_registry import DefaultToolRegistry
    from everstaff.tools.pipeline import ToolCallPipeline
    from everstaff.tools.stages import ExecutionStage
    from everstaff.nulls import InMemoryStore, NullTracer

    reg = DefaultToolRegistry()
    if tool:
        reg.register(tool)
    pipeline = ToolCallPipeline([ExecutionStage(reg)])
    return AgentContext(
        tool_registry=reg,
        memory=memory or InMemoryStore(),
        tool_pipeline=pipeline,
        tracer=NullTracer(),
        agent_name="parent-agent",
    )


@pytest.mark.asyncio
async def test_runtime_raises_on_unresolved_child_hitl():
    """When LLM finishes without resolving child HITL, runtime must raise HumanApprovalRequired."""
    from everstaff.core.runtime import AgentRuntime

    call_count = 0
    async def mock_complete(messages, tools, system=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return LLMResponse(
                content=None,
                tool_calls=[ToolCallRequest(id="c1", name="delegate_task_to_subagent",
                                            args={"agent_name": "child", "prompt": "do it"})],
            )
        else:
            # LLM ignores child HITL and responds normally
            return LLMResponse(content="I'm done!", tool_calls=[])

    llm = MagicMock()
    llm.complete_stream = None
    llm.complete = AsyncMock(side_effect=mock_complete)

    ctx = _make_ctx(tool=ChildHitlTool())
    runtime = AgentRuntime(context=ctx, llm_client=llm)

    with pytest.raises(HumanApprovalRequired) as exc_info:
        await runtime.run("test")

    assert len(exc_info.value.requests) >= 1
    assert exc_info.value.requests[0].origin_session_id == "child-sess"


@pytest.mark.asyncio
async def test_runtime_clears_child_hitl_on_resume():
    """When LLM calls delegate with resume_session_id, pending child HITLs should be cleared."""
    from everstaff.core.runtime import AgentRuntime

    call_count = 0
    async def mock_complete(messages, tools, system=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return LLMResponse(
                content=None,
                tool_calls=[ToolCallRequest(id="c1", name="delegate_task_to_subagent",
                                            args={"agent_name": "child", "prompt": "do it"})],
            )
        elif call_count == 2:
            # LLM properly resumes child
            return LLMResponse(
                content=None,
                tool_calls=[ToolCallRequest(id="c2", name="delegate_task_to_subagent",
                                            args={"agent_name": "child", "prompt": "continue",
                                                  "resume_session_id": "child-sess",
                                                  "hitl_response": {"decision": "approved"}})],
            )
        else:
            return LLMResponse(content="All done!", tool_calls=[])

    llm = MagicMock()
    llm.complete_stream = None
    llm.complete = AsyncMock(side_effect=mock_complete)

    ctx = _make_ctx(tool=ChildHitlTool())
    runtime = AgentRuntime(context=ctx, llm_client=llm)

    # Should complete normally, NOT raise HumanApprovalRequired
    result = await runtime.run("test")
    assert result  # non-empty response

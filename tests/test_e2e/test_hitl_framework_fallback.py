"""E2E: when parent LLM ignores child HITL, framework auto-raises HumanApprovalRequired."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from everstaff.core.runtime import AgentRuntime
from everstaff.core.context import AgentContext
from everstaff.tools.default_registry import DefaultToolRegistry
from everstaff.tools.pipeline import ToolCallPipeline
from everstaff.tools.stages import ExecutionStage
from everstaff.nulls import InMemoryStore, NullTracer
from everstaff.protocols import (
    HitlRequest, HumanApprovalRequired, LLMResponse,
    ToolCallRequest, ToolDefinition, ToolResult,
)


class FakeDelegateTool:
    """Simulates delegate_task_to_subagent returning a child HITL escalation."""
    @property
    def definition(self):
        return ToolDefinition("delegate_task_to_subagent", "delegate", {
            "type": "object",
            "properties": {"agent_name": {"type": "string"}, "prompt": {"type": "string"},
                           "resume_session_id": {"type": "string"}, "hitl_response": {"type": "object"}},
            "required": ["agent_name", "prompt"],
        })

    def __init__(self):
        self.call_count = 0

    async def execute(self, args):
        self.call_count += 1
        if args.get("resume_session_id"):
            # Resume call — child completes
            return ToolResult(tool_call_id="", content="Child completed successfully")
        # First call — child HITL escalation
        result = ToolResult(tool_call_id="", content="[SUB_AGENT_HITL]\nagent: child\nsession: child-s1")
        result._child_hitl_requests = [
            HitlRequest(hitl_id="h-c1", type="approve_reject", prompt="Deploy?",
                        origin_session_id="child-s1", origin_agent_name="child"),
        ]
        return result


def _build_ctx(tool):
    reg = DefaultToolRegistry()
    reg.register(tool)
    return AgentContext(
        tool_registry=reg,
        memory=InMemoryStore(),
        tool_pipeline=ToolCallPipeline([ExecutionStage(reg)]),
        tracer=NullTracer(),
        agent_name="parent",
    )


@pytest.mark.asyncio
async def test_framework_auto_escalates_ignored_child_hitl():
    """Full flow: delegate -> child HITL -> LLM ignores -> framework raises."""
    tool = FakeDelegateTool()
    ctx = _build_ctx(tool)

    call_count = 0
    async def mock_complete(messages, tools, system=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return LLMResponse(content=None, tool_calls=[
                ToolCallRequest(id="c1", name="delegate_task_to_subagent",
                                args={"agent_name": "child", "prompt": "deploy"}),
            ])
        else:
            # LLM ignores the child HITL and just responds
            return LLMResponse(content="All done!", tool_calls=[])

    llm = MagicMock()
    llm.complete_stream = None
    llm.complete = AsyncMock(side_effect=mock_complete)

    runtime = AgentRuntime(context=ctx, llm_client=llm)

    with pytest.raises(HumanApprovalRequired) as exc_info:
        await runtime.run("deploy the app")

    assert len(exc_info.value.requests) == 1
    assert exc_info.value.requests[0].hitl_id == "h-c1"
    assert exc_info.value.requests[0].origin_session_id == "child-s1"


@pytest.mark.asyncio
async def test_framework_does_not_escalate_when_llm_handles_child_hitl():
    """If LLM properly resumes the child via delegate, framework should NOT raise."""
    tool = FakeDelegateTool()
    ctx = _build_ctx(tool)

    llm_call = 0
    async def mock_complete(messages, tools, system=None):
        nonlocal llm_call
        llm_call += 1
        if llm_call == 1:
            return LLMResponse(content=None, tool_calls=[
                ToolCallRequest(id="c1", name="delegate_task_to_subagent",
                                args={"agent_name": "child", "prompt": "deploy"}),
            ])
        elif llm_call == 2:
            # LLM properly resumes child
            return LLMResponse(content=None, tool_calls=[
                ToolCallRequest(id="c2", name="delegate_task_to_subagent",
                                args={"agent_name": "child", "prompt": "continue",
                                      "resume_session_id": "child-s1",
                                      "hitl_response": {"decision": "approved"}}),
            ])
        else:
            return LLMResponse(content="All done!", tool_calls=[])

    llm = MagicMock()
    llm.complete_stream = None
    llm.complete = AsyncMock(side_effect=mock_complete)

    runtime = AgentRuntime(context=ctx, llm_client=llm)

    # Should complete normally
    result = await runtime.run("deploy the app")
    assert result  # non-empty


@pytest.mark.asyncio
async def test_framework_escalates_multiple_child_hitls():
    """When multiple children have unresolved HITLs, framework raises with all of them."""
    class MultiChildTool:
        @property
        def definition(self):
            return ToolDefinition("delegate_task_to_subagent", "delegate", {
                "type": "object",
                "properties": {"agent_name": {"type": "string"}, "prompt": {"type": "string"}},
                "required": ["agent_name", "prompt"],
            })

        def __init__(self):
            self.call_count = 0

        async def execute(self, args):
            self.call_count += 1
            result = ToolResult(tool_call_id="", content=f"[SUB_AGENT_HITL] child-{self.call_count}")
            result._child_hitl_requests = [
                HitlRequest(hitl_id=f"h-c{self.call_count}", type="approve_reject",
                            prompt=f"Question {self.call_count}?",
                            origin_session_id=f"child-s{self.call_count}",
                            origin_agent_name="child"),
            ]
            return result

    tool = MultiChildTool()
    ctx = _build_ctx(tool)

    call_count = 0
    async def mock_complete(messages, tools, system=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return LLMResponse(content=None, tool_calls=[
                ToolCallRequest(id="c1", name="delegate_task_to_subagent",
                                args={"agent_name": "child1", "prompt": "task1"}),
                ToolCallRequest(id="c2", name="delegate_task_to_subagent",
                                args={"agent_name": "child2", "prompt": "task2"}),
            ])
        else:
            return LLMResponse(content="Done", tool_calls=[])

    llm = MagicMock()
    llm.complete_stream = None
    llm.complete = AsyncMock(side_effect=mock_complete)

    runtime = AgentRuntime(context=ctx, llm_client=llm)

    with pytest.raises(HumanApprovalRequired) as exc_info:
        await runtime.run("do both tasks")

    assert len(exc_info.value.requests) == 2
    ids = {r.hitl_id for r in exc_info.value.requests}
    assert "h-c1" in ids
    assert "h-c2" in ids

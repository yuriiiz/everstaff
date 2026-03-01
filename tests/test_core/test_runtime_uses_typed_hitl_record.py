"""Runtime must produce HitlRequestRecord-compatible dicts in checkpoint."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from everstaff.protocols import (
    HitlRequest, HumanApprovalRequired, LLMResponse,
    ToolCallRequest, ToolDefinition, ToolResult,
)


class HitlTool:
    @property
    def definition(self):
        return ToolDefinition("ask_human", "ask", {"type": "object", "properties": {}})

    async def execute(self, args):
        raise HumanApprovalRequired([
            HitlRequest(hitl_id="h-typed", type="approve_reject", prompt="OK?")
        ])


@pytest.mark.asyncio
async def test_hitl_checkpoint_produces_valid_records():
    """hitl_requests saved to memory must be parseable as HitlRequestRecord."""
    from everstaff.core.runtime import AgentRuntime
    from everstaff.core.context import AgentContext
    from everstaff.tools.default_registry import DefaultToolRegistry
    from everstaff.tools.pipeline import ToolCallPipeline
    from everstaff.tools.stages import ExecutionStage
    from everstaff.nulls import InMemoryStore, NullTracer
    from everstaff.schema.hitl_models import HitlRequestRecord

    reg = DefaultToolRegistry()
    reg.register(HitlTool())
    mem = InMemoryStore()
    ctx = AgentContext(
        tool_registry=reg, memory=mem,
        tool_pipeline=ToolCallPipeline([ExecutionStage(reg)]),
        tracer=NullTracer(), agent_name="test",
    )

    llm = MagicMock()
    llm.complete_stream = None
    llm.complete = AsyncMock(return_value=LLMResponse(
        content=None, tool_calls=[ToolCallRequest(id="c1", name="ask_human", args={})],
    ))

    captured_kwargs = {}
    original_save = mem.save

    async def spy_save(session_id, messages, **kwargs):
        captured_kwargs.update(kwargs)
        return await original_save(session_id, messages, **kwargs)

    runtime = AgentRuntime(context=ctx, llm_client=llm)
    with patch.object(mem, 'save', side_effect=spy_save):
        with pytest.raises(HumanApprovalRequired):
            await runtime.run("test")

    hitl_requests = captured_kwargs.get("hitl_requests", [])
    assert len(hitl_requests) >= 1
    # Verify each one is valid HitlRequestRecord
    for item in hitl_requests:
        record = HitlRequestRecord.model_validate(item)
        assert record.hitl_id == "h-typed"
        assert record.request.type == "approve_reject"
        assert record.status == "pending"

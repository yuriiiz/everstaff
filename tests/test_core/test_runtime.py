import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from everstaff.protocols import LLMResponse, ToolCallRequest, ToolDefinition, ToolResult, Message


def make_context(tool_registry=None, memory=None):
    from everstaff.tools.default_registry import DefaultToolRegistry
    from everstaff.nulls import InMemoryStore
    from everstaff.tools.pipeline import ToolCallPipeline
    from everstaff.tools.stages import ExecutionStage
    from everstaff.core.context import AgentContext

    reg = tool_registry or DefaultToolRegistry()
    mem = memory or InMemoryStore()
    pipeline = ToolCallPipeline([ExecutionStage(reg)])
    return AgentContext(tool_registry=reg, memory=mem, tool_pipeline=pipeline)


def _make_ctx(tracer=None, memory=None, cancellation=None):
    from everstaff.core.context import AgentContext
    from everstaff.tools.pipeline import ToolCallPipeline
    from everstaff.tools.stages import ExecutionStage
    from everstaff.tools.default_registry import DefaultToolRegistry
    from everstaff.nulls import InMemoryStore, NullTracer
    reg = DefaultToolRegistry()
    pipeline = ToolCallPipeline([ExecutionStage(reg)])
    kwargs = dict(
        tool_registry=reg,
        memory=memory or InMemoryStore(),
        tool_pipeline=pipeline,
        tracer=tracer or NullTracer(),
        agent_name="test-agent",
    )
    if cancellation is not None:
        kwargs["cancellation"] = cancellation
    return AgentContext(**kwargs)


class EchoTool:
    @property
    def definition(self):
        return ToolDefinition("echo", "echo", {"type": "object", "properties": {"msg": {"type": "string"}}})

    async def execute(self, args):
        return ToolResult(tool_call_id="", content=args["msg"])


@pytest.mark.asyncio
async def test_runtime_returns_final_response():
    from everstaff.core.runtime import AgentRuntime

    llm = MagicMock()
    llm.complete_stream = None  # prevent AsyncMock auto-attribute from triggering streaming path
    llm.complete = AsyncMock(return_value=LLMResponse(content="Hello!", tool_calls=[]))

    ctx = make_context()
    runtime = AgentRuntime(context=ctx, llm_client=llm)
    result = await runtime.run("Hi")
    assert result == "Hello!"


@pytest.mark.asyncio
async def test_runtime_executes_tool_call_then_returns():
    from everstaff.core.runtime import AgentRuntime
    from everstaff.tools.default_registry import DefaultToolRegistry

    reg = DefaultToolRegistry()
    reg.register(EchoTool())

    call_count = 0
    async def fake_complete(messages, tools, system=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return LLMResponse(
                content=None,
                tool_calls=[ToolCallRequest(id="c1", name="echo", args={"msg": "world"})],
            )
        return LLMResponse(content="done", tool_calls=[])

    llm = MagicMock()
    llm.complete_stream = None  # prevent AsyncMock auto-attribute from triggering streaming path
    llm.complete = AsyncMock(side_effect=fake_complete)

    ctx = make_context(tool_registry=reg)
    runtime = AgentRuntime(context=ctx, llm_client=llm)
    result = await runtime.run("test")
    assert result == "done"
    assert call_count == 2


@pytest.mark.asyncio
async def test_runtime_persists_messages_to_memory():
    from everstaff.core.runtime import AgentRuntime
    from everstaff.nulls import InMemoryStore

    llm = MagicMock()
    llm.complete_stream = None  # prevent AsyncMock auto-attribute from triggering streaming path
    llm.complete = AsyncMock(return_value=LLMResponse(content="saved", tool_calls=[]))

    mem = InMemoryStore()
    ctx = make_context(memory=mem)
    runtime = AgentRuntime(context=ctx, llm_client=llm)
    await runtime.run("persist me")

    saved = await mem.load(ctx.session_id)
    assert len(saved) == 2
    assert saved[0].role == "user"
    assert saved[1].role == "assistant"


@pytest.mark.asyncio
async def test_runtime_loads_existing_session():
    from everstaff.core.runtime import AgentRuntime
    from everstaff.nulls import InMemoryStore

    mem = InMemoryStore()
    session_id = "existing-session"
    existing = [
        Message(role="user", content="previous message"),
        Message(role="assistant", content="previous reply"),
    ]
    await mem.save(session_id, existing)

    received_messages: list = []
    async def fake_complete(messages, tools, system=None):
        received_messages.extend(messages)
        return LLMResponse(content="new reply", tool_calls=[])

    llm = MagicMock()
    llm.complete_stream = None  # prevent AsyncMock auto-attribute from triggering streaming path
    llm.complete = AsyncMock(side_effect=fake_complete)

    from everstaff.tools.default_registry import DefaultToolRegistry
    from everstaff.tools.pipeline import ToolCallPipeline
    from everstaff.tools.stages import ExecutionStage
    from everstaff.core.context import AgentContext

    reg = DefaultToolRegistry()
    pipeline = ToolCallPipeline([ExecutionStage(reg)])
    ctx = AgentContext(
        tool_registry=reg,
        memory=mem,
        tool_pipeline=pipeline,
        session_id=session_id,
    )
    runtime = AgentRuntime(context=ctx, llm_client=llm)
    await runtime.run("new message")

    assert len(received_messages) == 3
    assert received_messages[0].content == "previous message"
    assert received_messages[2].content == "new message"


@pytest.mark.asyncio
async def test_runtime_injects_skill_provider_prompt():
    from everstaff.core.runtime import AgentRuntime
    from everstaff.core.context import AgentContext
    from everstaff.tools.pipeline import ToolCallPipeline
    from everstaff.tools.stages import ExecutionStage
    from everstaff.tools.default_registry import DefaultToolRegistry
    from everstaff.nulls import InMemoryStore
    from unittest.mock import AsyncMock, MagicMock
    from everstaff.protocols import LLMResponse

    class FakeSkillProvider:
        def get_tools(self): return []
        def get_prompt_injection(self): return "## Skills\n- skill_a"

    class FakeKnowledgeProvider:
        def get_tools(self): return []
        def get_prompt_injection(self): return ""

    class FakeSubAgentProvider:
        def get_tools(self): return []
        def get_prompt_injection(self): return ""

    class FakeMcpProvider:
        def get_tools(self): return []
        def get_prompt_injection(self): return ""

    reg = DefaultToolRegistry()
    pipeline = ToolCallPipeline([ExecutionStage(reg)])
    ctx = AgentContext(
        tool_registry=reg,
        memory=InMemoryStore(),
        tool_pipeline=pipeline,
        system_prompt="Base instructions.",
        skill_provider=FakeSkillProvider(),
        knowledge_provider=FakeKnowledgeProvider(),
        sub_agent_provider=FakeSubAgentProvider(),
        mcp_provider=FakeMcpProvider(),
    )

    received_system: list = []
    llm = MagicMock()
    llm.complete_stream = None  # prevent AsyncMock auto-attribute from triggering streaming path
    async def capture_complete(messages, tools, system=None):
        received_system.append(system)
        return LLMResponse(content="ok", tool_calls=[])
    llm.complete = AsyncMock(side_effect=capture_complete)

    runtime = AgentRuntime(context=ctx, llm_client=llm)
    await runtime.run("hi")

    assert received_system[0] is not None
    assert "Base instructions." in received_system[0]
    assert "## Skills" in received_system[0]


@pytest.mark.asyncio
async def test_runtime_system_prompt_none_when_no_injections():
    from everstaff.core.runtime import AgentRuntime
    from unittest.mock import AsyncMock, MagicMock
    from everstaff.protocols import LLMResponse

    ctx = make_context()  # uses NullSkillProvider etc, no system_prompt
    received_system: list = []
    llm = MagicMock()
    llm.complete_stream = None  # prevent AsyncMock auto-attribute from triggering streaming path
    async def capture(messages, tools, system=None):
        received_system.append(system)
        return LLMResponse(content="ok", tool_calls=[])
    llm.complete = AsyncMock(side_effect=capture)

    runtime = AgentRuntime(context=ctx, llm_client=llm)
    await runtime.run("hi")
    assert received_system[0] is None


@pytest.mark.asyncio
async def test_runtime_emits_session_start_and_end():
    from everstaff.core.runtime import AgentRuntime
    from everstaff.protocols import LLMResponse
    events = []

    class SpyTracer:
        def on_event(self, e): events.append(e.kind)

    ctx = _make_ctx(tracer=SpyTracer())
    llm = MagicMock()
    llm.complete_stream = None  # prevent AsyncMock auto-attribute from triggering streaming path
    llm.complete = AsyncMock(return_value=LLMResponse(content="hi", tool_calls=[]))
    runtime = AgentRuntime(ctx, llm)
    await runtime.run("hello")

    assert "session_start" in events
    assert "session_end" in events
    assert "user_input" in events
    assert "llm_start" in events
    assert "llm_end" in events


@pytest.mark.asyncio
async def test_runtime_stops_when_cancelled():
    from everstaff.core.runtime import AgentRuntime
    from everstaff.protocols import LLMResponse

    ctx = _make_ctx()
    ctx.cancellation.cancel()  # pre-cancel

    llm = MagicMock()
    llm.complete_stream = None  # prevent AsyncMock auto-attribute from triggering streaming path
    llm.complete = AsyncMock(return_value=LLMResponse(content="hi", tool_calls=[]))
    runtime = AgentRuntime(ctx, llm)
    result = await runtime.run("hello")

    assert "[Stopped]" in result
    llm.complete.assert_not_called()  # cancelled before first LLM call


@pytest.mark.asyncio
async def test_runtime_emits_tool_events():
    from everstaff.core.runtime import AgentRuntime
    from everstaff.protocols import LLMResponse, ToolCallRequest
    events = []

    class SpyTracer:
        def on_event(self, e): events.append(e.kind)

    from unittest.mock import patch
    ctx = _make_ctx(tracer=SpyTracer())
    llm = MagicMock()
    llm.complete_stream = None  # prevent AsyncMock auto-attribute from triggering streaming path

    # First call returns a tool_call, second returns final response
    llm.complete = AsyncMock(side_effect=[
        LLMResponse(content=None, tool_calls=[ToolCallRequest(id="tc1", name="read_file", args={"path": "x.py"})]),
        LLMResponse(content="done", tool_calls=[]),
    ])
    runtime = AgentRuntime(ctx, llm)
    with patch.object(ctx.tool_pipeline, "execute", new=AsyncMock(return_value=MagicMock(content="file content", is_error=False, tool_call_id="tc1"))):
        await runtime.run("read x.py")

    assert "tool_start" in events
    assert "tool_end" in events


@pytest.mark.asyncio
async def test_tool_call_arguments_are_valid_json():
    """arguments in the assistant message must be a valid JSON string, not str(dict)."""
    from everstaff.core.runtime import AgentRuntime
    from everstaff.tools.default_registry import DefaultToolRegistry

    ctx = _make_ctx()
    ctx.tool_registry.register(EchoTool())

    llm_calls = []

    async def fake_complete(messages, tools, system=None):
        llm_calls.append(messages)
        if len(llm_calls) == 1:
            return LLMResponse(
                content=None,
                tool_calls=[ToolCallRequest(id="tc1", name="echo", args={"msg": "hello"})],
            )
        return LLMResponse(content="done", tool_calls=[])

    llm = MagicMock()
    llm.complete_stream = None  # prevent AsyncMock auto-attribute from triggering streaming path
    llm.complete = AsyncMock(side_effect=fake_complete)

    runtime = AgentRuntime(context=ctx, llm_client=llm)
    await runtime.run("hi")

    # Second LLM call has the assistant message with tool_calls
    second_call_messages = llm_calls[1]
    assistant_msg = next(m for m in second_call_messages if m.role == "assistant")
    raw_args = assistant_msg.tool_calls[0]["function"]["arguments"]

    # Must be valid JSON (not Python repr with single quotes)
    parsed = json.loads(raw_args)  # raises JSONDecodeError if not valid JSON
    assert parsed == {"msg": "hello"}


@pytest.mark.asyncio
async def test_runtime_passes_stats_to_memory_save():
    """Runtime must collect SessionStats and pass them to memory.save()."""
    from everstaff.schema.token_stats import SessionStats
    from everstaff.core.runtime import AgentRuntime

    saved_kwargs = {}

    class CapturingMemory:
        async def load(self, session_id): return []
        async def save(self, session_id, messages, **kwargs):
            saved_kwargs.update(kwargs)

    from everstaff.core.context import AgentContext
    from everstaff.tools.pipeline import ToolCallPipeline
    from everstaff.tools.stages import ExecutionStage
    from everstaff.tools.default_registry import DefaultToolRegistry
    from everstaff.nulls import NullTracer

    reg = DefaultToolRegistry()
    mem = CapturingMemory()
    pipeline = ToolCallPipeline([ExecutionStage(reg)])
    ctx = AgentContext(
        tool_registry=reg, memory=mem, tool_pipeline=pipeline,
        tracer=NullTracer(), agent_name="test-agent",
    )

    response = LLMResponse(content="Hello!", tool_calls=[])
    response.input_tokens = 10
    response.output_tokens = 5
    llm = MagicMock()
    llm.complete_stream = None  # prevent AsyncMock auto-attribute from triggering streaming path
    llm.complete = AsyncMock(return_value=response)

    runtime = AgentRuntime(context=ctx, llm_client=llm)
    await runtime.run("Hi")

    assert "stats" in saved_kwargs, "runtime must pass stats= to memory.save()"
    assert isinstance(saved_kwargs["stats"], SessionStats)


@pytest.mark.asyncio
async def test_runtime_returns_hitl_sentinel_when_tool_raises():
    """When a tool raises HumanApprovalRequired, runtime.run() re-raises it."""
    from everstaff.core.runtime import AgentRuntime
    from everstaff.protocols import HumanApprovalRequired, HitlRequest, ToolCallRequest

    hitl_request = HitlRequest(
        hitl_id="test-hitl-uuid",
        type="approve_reject",
        prompt="Do you approve?",
    )

    call_count = 0
    async def fake_complete(messages, tools, system=None):
        nonlocal call_count
        call_count += 1
        return LLMResponse(
            content=None,
            tool_calls=[ToolCallRequest(id="c1", name="request_human_input", args={"type": "approve_reject", "prompt": "Do you approve?"})],
        )

    llm = MagicMock()
    llm.complete_stream = None  # prevent AsyncMock auto-attribute from triggering streaming path
    llm.complete = AsyncMock(side_effect=fake_complete)

    ctx = _make_ctx()
    runtime = AgentRuntime(context=ctx, llm_client=llm)

    from unittest.mock import patch
    with pytest.raises(HumanApprovalRequired) as exc_info:
        with patch.object(ctx.tool_pipeline, "execute", side_effect=HumanApprovalRequired(hitl_request)):
            await runtime.run("please approve")

    assert exc_info.value.requests[0].hitl_id == "test-hitl-uuid"


@pytest.mark.asyncio
async def test_runtime_saves_paused_status_on_hitl():
    """When HITL fires, memory.save is called with status='paused'."""
    from everstaff.core.runtime import AgentRuntime
    from everstaff.protocols import HumanApprovalRequired, HitlRequest, ToolCallRequest

    hitl_request = HitlRequest(
        hitl_id="paused-hitl-uuid",
        type="provide_input",
        prompt="Please provide input",
    )

    saved_statuses = []

    class CapturingMemory:
        async def load(self, session_id): return []
        async def save(self, session_id, messages, **kwargs):
            if "status" in kwargs:
                saved_statuses.append(kwargs["status"])

    from everstaff.core.context import AgentContext
    from everstaff.tools.pipeline import ToolCallPipeline
    from everstaff.tools.stages import ExecutionStage
    from everstaff.tools.default_registry import DefaultToolRegistry
    from everstaff.nulls import NullTracer

    reg = DefaultToolRegistry()
    mem = CapturingMemory()
    pipeline = ToolCallPipeline([ExecutionStage(reg)])
    ctx = AgentContext(
        tool_registry=reg, memory=mem, tool_pipeline=pipeline,
        tracer=NullTracer(), agent_name="test-agent",
    )

    llm = MagicMock()
    llm.complete_stream = None  # prevent AsyncMock auto-attribute from triggering streaming path
    llm.complete = AsyncMock(return_value=LLMResponse(
        content=None,
        tool_calls=[ToolCallRequest(id="c1", name="request_human_input", args={"type": "provide_input", "prompt": "Please provide input"})],
    ))

    runtime = AgentRuntime(context=ctx, llm_client=llm)
    from unittest.mock import patch
    with pytest.raises(HumanApprovalRequired):
        with patch.object(ctx.tool_pipeline, "execute", side_effect=HumanApprovalRequired(hitl_request)):
            await runtime.run("need input")

    assert "waiting_for_human" in saved_statuses, f"Expected 'waiting_for_human' status, got: {saved_statuses}"


@pytest.mark.asyncio
async def test_runtime_emits_hitl_requested_trace():
    """When HITL fires, the 'hitl_requested' trace event is emitted."""
    from everstaff.core.runtime import AgentRuntime
    from everstaff.protocols import HumanApprovalRequired, HitlRequest, ToolCallRequest, LLMResponse

    hitl_request = HitlRequest(
        hitl_id="trace-hitl-uuid",
        type="approve_reject",
        prompt="Approve?",
    )

    events = []

    class SpyTracer:
        def on_event(self, e):
            events.append(e.kind)

    ctx = _make_ctx(tracer=SpyTracer())
    llm = MagicMock()
    llm.complete_stream = None  # prevent AsyncMock auto-attribute from triggering streaming path
    llm.complete = AsyncMock(return_value=LLMResponse(
        content=None,
        tool_calls=[ToolCallRequest(id="c1", name="request_human_input", args={"type": "approve_reject", "prompt": "Approve?"})],
    ))

    runtime = AgentRuntime(context=ctx, llm_client=llm)
    from unittest.mock import patch
    with pytest.raises(HumanApprovalRequired):
        with patch.object(ctx.tool_pipeline, "execute", side_effect=HumanApprovalRequired(hitl_request)):
            await runtime.run("approve this")

    assert "hitl_requested" in events, f"Expected 'hitl_requested' event, got: {events}"


@pytest.mark.asyncio
async def test_runtime_generates_title_after_first_reply():
    """After first turn, LLM is called a second time to generate a title."""
    import asyncio
    from unittest.mock import AsyncMock
    from everstaff.core.runtime import AgentRuntime
    from everstaff.core.context import AgentContext
    from everstaff.protocols import LLMResponse
    from everstaff.nulls import NullTracer, AllowAllChecker
    from everstaff.tools.pipeline import ToolCallPipeline
    from everstaff.tools.stages import ExecutionStage, PermissionStage
    from everstaff.tools.default_registry import DefaultToolRegistry

    registry = DefaultToolRegistry()
    pipeline = ToolCallPipeline([PermissionStage(AllowAllChecker()), ExecutionStage(registry)])

    memory = AsyncMock()
    memory.load = AsyncMock(return_value=[])
    memory.save = AsyncMock()

    # First call = main response, second call = title extraction
    main_response = LLMResponse(content="Here is the answer.", tool_calls=[])
    title_response = LLMResponse(content="data analysis task", tool_calls=[])
    llm = AsyncMock()
    llm.complete_stream = None  # prevent AsyncMock auto-attribute from triggering streaming path
    llm.complete = AsyncMock(side_effect=[main_response, title_response])

    ctx = AgentContext(
        tool_registry=registry,
        memory=memory,
        tool_pipeline=pipeline,
        agent_name="test-agent",
        session_id="sess-title-test",
        tracer=NullTracer(),
    )
    runtime = AgentRuntime(context=ctx, llm_client=llm)
    await runtime.run("Analyze this data")

    # Allow background task to complete
    await asyncio.sleep(0.1)

    # memory.save should have been called at least once (main save)
    assert memory.save.call_count >= 1
    # The title extraction LLM call should have happened (2 total calls)
    assert llm.complete.call_count == 2

    # Verify title was actually persisted
    save_calls_with_title = [
        c for c in memory.save.call_args_list
        if c.kwargs.get("title") == "data analysis task"
    ]
    assert len(save_calls_with_title) == 1, f"Expected 1 save with title, got: {memory.save.call_args_list}"


@pytest.mark.asyncio
async def test_runtime_writes_cancelled_status_on_cancel():
    """When cancellation fires, session status is saved as 'cancelled'."""
    from everstaff.core.runtime import AgentRuntime
    from everstaff.protocols import CancellationEvent

    saved_statuses = []

    class CapturingMemory:
        async def load(self, sid):
            return []
        async def save(self, sid, msgs, **kw):
            if "status" in kw:
                saved_statuses.append(kw["status"])

    cancellation = CancellationEvent()
    ctx = _make_ctx(memory=CapturingMemory(), cancellation=cancellation)
    # Cancel immediately
    cancellation.cancel()

    from unittest.mock import MagicMock
    runtime = AgentRuntime(context=ctx, llm_client=MagicMock())
    async for _ in runtime.run_stream("hello"):
        pass

    assert "cancelled" in saved_statuses, f"Expected 'cancelled', got: {saved_statuses}"


@pytest.mark.asyncio
async def test_runtime_writes_failed_status_on_exception():
    """When LLM raises, session status is saved as 'failed'."""
    from everstaff.core.runtime import AgentRuntime
    from unittest.mock import AsyncMock, MagicMock

    saved_statuses = []

    class CapturingMemory:
        async def load(self, sid):
            return []
        async def save(self, sid, msgs, **kw):
            if "status" in kw:
                saved_statuses.append(kw["status"])

    ctx = _make_ctx(memory=CapturingMemory())
    llm = MagicMock()
    llm.complete_stream = None  # prevent AsyncMock auto-attribute from triggering streaming path
    llm.complete = AsyncMock(side_effect=RuntimeError("LLM exploded"))

    runtime = AgentRuntime(context=ctx, llm_client=llm)
    with pytest.raises(RuntimeError):
        async for _ in runtime.run_stream("hello"):
            pass

    assert "failed" in saved_statuses, f"Expected 'failed', got: {saved_statuses}"


@pytest.mark.asyncio
async def test_generate_title_emits_trace_events():
    """_generate_title must emit llm_start and llm_end trace events."""
    from everstaff.core.runtime import AgentRuntime
    from everstaff.protocols import LLMResponse, TraceEvent

    events = []

    class CapturingTracer:
        def on_event(self, event: TraceEvent) -> None:
            events.append(event)

    llm = MagicMock()
    llm.complete_stream = None  # prevent AsyncMock auto-attribute from triggering streaming path
    llm.complete = AsyncMock(return_value=LLMResponse(content="My Title", tool_calls=[]))

    ctx = _make_ctx(tracer=CapturingTracer())
    runtime = AgentRuntime(context=ctx, llm_client=llm)
    await runtime._generate_title("Hello user input", "World assistant response")

    kinds = [e.kind for e in events]
    assert "llm_start" in kinds, f"Expected llm_start in {kinds}"
    assert "llm_end" in kinds, f"Expected llm_end in {kinds}"

    title_events = [e for e in events if e.data.get("purpose") == "title_generation"]
    assert len(title_events) >= 2, f"Expected at least 2 title_generation events, got {len(title_events)}"


@pytest.mark.asyncio
async def test_generate_title_calls_hooks():
    """_generate_title must call on_llm_start and on_llm_end hooks."""
    from everstaff.core.runtime import AgentRuntime
    from everstaff.protocols import LLMResponse

    hook_calls = []

    class CapturingHook:
        async def on_session_start(self, ctx): pass
        async def on_session_end(self, ctx, r): pass
        async def on_user_input(self, ctx, c): return c
        async def on_llm_start(self, ctx, msgs): hook_calls.append("llm_start"); return msgs
        async def on_llm_end(self, ctx, r): hook_calls.append("llm_end"); return r
        async def on_tool_start(self, ctx, a, n): return a
        async def on_tool_end(self, ctx, r, n): return r
        async def on_subagent_start(self, ctx, n, p): return p
        async def on_subagent_end(self, ctx, n, r): pass
        async def on_memory_compact(self, ctx, b, a): pass
        async def on_error(self, ctx, e, p): pass

    llm = MagicMock()
    llm.complete_stream = None  # prevent AsyncMock auto-attribute from triggering streaming path
    llm.complete = AsyncMock(return_value=LLMResponse(content="Short title", tool_calls=[]))

    from everstaff.nulls import InMemoryStore, NullTracer
    from everstaff.core.context import AgentContext
    from everstaff.tools.pipeline import ToolCallPipeline
    from everstaff.tools.stages import ExecutionStage
    from everstaff.tools.default_registry import DefaultToolRegistry
    reg = DefaultToolRegistry()
    pipeline = ToolCallPipeline([ExecutionStage(reg)])
    ctx = AgentContext(
        tool_registry=reg,
        memory=InMemoryStore(),
        tool_pipeline=pipeline,
        tracer=NullTracer(),
        agent_name="test",
        hooks=[CapturingHook()],
    )
    runtime = AgentRuntime(context=ctx, llm_client=llm)
    await runtime._generate_title("hello", "world")

    assert "llm_start" in hook_calls, f"Expected on_llm_start hook to be called, got: {hook_calls}"
    assert "llm_end" in hook_calls, f"Expected on_llm_end hook to be called, got: {hook_calls}"


@pytest.mark.asyncio
async def test_runtime_writes_waiting_for_human_status_on_hitl():
    """HumanApprovalRequired saves status='waiting_for_human' (not 'paused')."""
    from everstaff.protocols import HumanApprovalRequired, HitlRequest, ToolCallRequest, LLMResponse
    from everstaff.core.runtime import AgentRuntime
    from unittest.mock import AsyncMock, MagicMock, patch

    saved_statuses = []

    class CapturingMemory:
        async def load(self, sid):
            return []
        async def save(self, sid, msgs, **kw):
            if "status" in kw:
                saved_statuses.append(kw["status"])

    ctx = _make_ctx(memory=CapturingMemory())
    hitl_req = HitlRequest(hitl_id="h1", type="approve_reject", prompt="Approve?")

    llm = MagicMock()
    llm.complete_stream = None  # prevent AsyncMock auto-attribute from triggering streaming path
    llm.complete = AsyncMock(return_value=LLMResponse(
        content=None,
        tool_calls=[ToolCallRequest(id="c1", name="request_human_input",
                                    args={"type": "approve_reject", "prompt": "Approve?"})],
    ))

    runtime = AgentRuntime(context=ctx, llm_client=llm)
    with pytest.raises(HumanApprovalRequired):
        with patch.object(ctx.tool_pipeline, "execute", side_effect=HumanApprovalRequired(hitl_req)):
            async for _ in runtime.run_stream("do it"):
                pass

    assert "waiting_for_human" in saved_statuses, f"Expected 'waiting_for_human', got: {saved_statuses}"


@pytest.mark.asyncio
async def test_runtime_hitl_checkpoint_includes_tool_call_id():
    """When HITL fires, session.json hitl_requests must contain the tool_call_id for proper resume."""
    from everstaff.core.runtime import AgentRuntime
    from everstaff.protocols import HumanApprovalRequired, HitlRequest, ToolCallRequest, LLMResponse

    saved_kwargs = {}

    class CapturingMemory:
        async def load(self, sid): return []
        async def save(self, sid, msgs, **kw):
            saved_kwargs.update(kw)

    hitl_req = HitlRequest(hitl_id="h1", type="approve_reject", prompt="Approve?")
    llm = MagicMock()
    llm.complete_stream = None  # prevent AsyncMock auto-attribute from triggering streaming path
    llm.complete = AsyncMock(return_value=LLMResponse(
        content=None,
        tool_calls=[ToolCallRequest(id="tc-abc", name="request_human_input",
                                    args={"type": "approve_reject", "prompt": "Approve?"})],
    ))
    ctx = _make_ctx(memory=CapturingMemory())
    runtime = AgentRuntime(context=ctx, llm_client=llm)
    from unittest.mock import patch
    with pytest.raises(HumanApprovalRequired):
        with patch.object(ctx.tool_pipeline, "execute", side_effect=HumanApprovalRequired(hitl_req)):
            async for _ in runtime.run_stream("do it"):
                pass

    hitl_requests = saved_kwargs.get("hitl_requests", [])
    assert len(hitl_requests) == 1, f"Expected 1 HITL in session.json, got: {hitl_requests}"
    assert hitl_requests[0]["tool_call_id"] == "tc-abc", (
        f"tool_call_id not in session.json hitl_requests: {hitl_requests[0]}"
    )


@pytest.mark.asyncio
async def test_runtime_stats_persisted_after_llm_call():
    """own_calls in session metadata must be non-empty after at least one LLM call completes."""
    from everstaff.core.runtime import AgentRuntime
    from everstaff.protocols import LLMResponse

    saved_stats = []

    class CapturingMemory:
        async def load(self, sid): return []
        async def save(self, sid, msgs, **kw):
            if kw.get("stats") is not None:
                saved_stats.append(kw["stats"])

    llm = MagicMock()
    llm.complete_stream = None  # prevent AsyncMock auto-attribute from triggering streaming path
    response = LLMResponse(content="done", tool_calls=[])
    response.input_tokens = 10
    response.output_tokens = 5
    llm.complete = AsyncMock(return_value=response)

    ctx = _make_ctx(memory=CapturingMemory())
    runtime = AgentRuntime(context=ctx, llm_client=llm)
    await runtime.run("hello")

    assert saved_stats, "memory.save() was never called with stats"
    final_stats = saved_stats[-1]
    assert len(final_stats.own_calls) > 0, \
        f"own_calls is empty — token usage not recorded. stats={final_stats}"
    assert final_stats.own_calls[0].input_tokens == 10


@pytest.mark.asyncio
async def test_runtime_merges_child_stats_into_own_stats():
    """When a tool returns child_stats, runtime must merge them into session children_calls."""
    from everstaff.core.runtime import AgentRuntime
    from everstaff.protocols import LLMResponse, ToolCallRequest, ToolResult
    from everstaff.schema.token_stats import SessionStats, TokenUsage

    child_stats = SessionStats()
    child_stats.record(TokenUsage(input_tokens=30, output_tokens=15, total_tokens=45, model_id="gpt-4"))

    saved_stats = []

    class CapturingMemory:
        async def load(self, sid): return []
        async def save(self, sid, msgs, **kw):
            if kw.get("stats") is not None:
                saved_stats.append(kw["stats"])

    ctx = _make_ctx(memory=CapturingMemory())
    ctx.tool_registry.register(EchoTool())

    call_count = 0
    async def fake_complete(messages, tools, system=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return LLMResponse(
                content=None,
                tool_calls=[ToolCallRequest(id="tc1", name="echo", args={"msg": "hi"})],
            )
        return LLMResponse(content="done", tool_calls=[])

    llm = MagicMock()
    llm.complete_stream = None  # prevent AsyncMock auto-attribute from triggering streaming path
    llm.complete = AsyncMock(side_effect=fake_complete)
    llm.model_id = "gpt-4"

    runtime = AgentRuntime(context=ctx, llm_client=llm)

    tool_result_with_stats = ToolResult(tool_call_id="tc1", content="hi", child_stats=child_stats)
    with patch.object(ctx.tool_pipeline, "execute", new=AsyncMock(return_value=tool_result_with_stats)):
        await runtime.run("hello")

    assert saved_stats, "No stats were saved"
    final_stats = saved_stats[-1]
    assert len(final_stats.children_calls) > 0, \
        f"children_calls is empty — child stats not merged. children_calls={final_stats.children_calls}"
    assert final_stats.children_calls[0].input_tokens == 30


@pytest.mark.asyncio
async def test_runtime_flushes_tracer_after_normal_completion():
    """run_stream() must call tracer.aflush() after session ends normally."""
    from everstaff.core.runtime import AgentRuntime
    from everstaff.protocols import LLMResponse

    flushed = []

    class TrackingTracer:
        def on_event(self, e): pass
        async def aflush(self): flushed.append(True)

    ctx = _make_ctx(tracer=TrackingTracer())
    llm = MagicMock()
    llm.complete_stream = None  # prevent AsyncMock auto-attribute from triggering streaming path
    llm.complete = AsyncMock(return_value=LLMResponse(content="done", tool_calls=[]))
    runtime = AgentRuntime(ctx, llm)
    async for _ in runtime.run_stream("hello"):
        pass

    assert flushed, "tracer.aflush() was never called after normal session completion"


@pytest.mark.asyncio
async def test_runtime_flushes_tracer_after_cancellation():
    """run_stream() must call tracer.aflush() even when cancelled."""
    from everstaff.core.runtime import AgentRuntime
    from everstaff.protocols import CancellationEvent

    flushed = []

    class TrackingTracer:
        def on_event(self, e): pass
        async def aflush(self): flushed.append(True)

    cancellation = CancellationEvent()
    cancellation.cancel()
    ctx = _make_ctx(tracer=TrackingTracer(), cancellation=cancellation)
    runtime = AgentRuntime(ctx, llm_client=MagicMock())
    async for _ in runtime.run_stream("hello"):
        pass

    assert flushed, "tracer.aflush() was never called after cancellation"


@pytest.mark.asyncio
async def test_runtime_flushes_tracer_after_hitl():
    """run_stream() must call tracer.aflush() when paused for HITL."""
    from everstaff.core.runtime import AgentRuntime
    from everstaff.protocols import HumanApprovalRequired, HitlRequest, ToolCallRequest, LLMResponse

    flushed = []

    class TrackingTracer:
        def on_event(self, e): pass
        async def aflush(self): flushed.append(True)

    ctx = _make_ctx(tracer=TrackingTracer())
    hitl_req = HitlRequest(hitl_id="h1", type="approve_reject", prompt="Approve?")
    llm = MagicMock()
    llm.complete_stream = None  # prevent AsyncMock auto-attribute from triggering streaming path
    llm.complete = AsyncMock(return_value=LLMResponse(
        content=None,
        tool_calls=[ToolCallRequest(id="c1", name="request_human_input",
                                    args={"type": "approve_reject", "prompt": "Approve?"})],
    ))
    runtime = AgentRuntime(ctx, llm)
    from unittest.mock import patch
    with pytest.raises(HumanApprovalRequired):
        with patch.object(ctx.tool_pipeline, "execute", side_effect=HumanApprovalRequired(hitl_req)):
            async for _ in runtime.run_stream("approve"):
                pass

    assert flushed, "tracer.aflush() was never called after HITL pause"


@pytest.mark.asyncio
async def test_runtime_truncates_dangling_tool_calls_on_load():
    """When history ends with assistant+tool_calls but no matching tool results,
    runtime must truncate that incomplete turn so LLM does not receive an invalid
    sequence (assistant+tool_calls → user) that causes error 2013."""
    from everstaff.core.runtime import AgentRuntime
    from everstaff.protocols import LLMResponse, Message
    from everstaff.nulls import InMemoryStore

    # Build history with a dangling assistant tool_call at the end
    history = [
        Message(role="user", content="hello"),
        Message(role="assistant", content="let me call a tool",
                tool_calls=[{"id": "tc-dangling", "name": "some_tool", "arguments": "{}"}]),
        # NOTE: no role=tool message follows — this is the dangling state
    ]

    mem = InMemoryStore()
    await mem.save("sess-dangle", history)

    call_count = 0
    received_messages = []

    async def fake_complete(messages, tools, system=None):
        nonlocal call_count
        call_count += 1
        received_messages.extend(messages)
        return LLMResponse(content="done after truncation", tool_calls=[])

    llm = MagicMock()
    llm.complete_stream = None  # prevent AsyncMock auto-attribute from triggering streaming path
    llm.complete = AsyncMock(side_effect=fake_complete)
    llm.model_id = "gpt-4"

    ctx = _make_ctx(memory=mem)
    ctx.session_id = "sess-dangle"
    runtime = AgentRuntime(context=ctx, llm_client=llm)

    await runtime.run("new user turn")

    # The LLM must NOT have received the dangling assistant message with tool_calls
    dangling_msgs = [
        m for m in received_messages
        if m.role == "assistant" and m.tool_calls
    ]
    assert not dangling_msgs, (
        "Runtime sent dangling assistant+tool_calls to LLM — "
        "this causes Minimax error 2013. "
        f"Messages sent: {[m.role for m in received_messages]}"
    )

    # The new user message must still be present
    user_msgs = [m for m in received_messages if m.role == "user"]
    assert any("new user turn" in str(m.content or "") for m in user_msgs), \
        "New user message was not sent to LLM"


@pytest.mark.asyncio
async def test_runtime_preserves_fully_completed_tool_calls_on_load():
    """History where all tool_calls have matching tool results must NOT be truncated."""
    from everstaff.core.runtime import AgentRuntime
    from everstaff.protocols import LLMResponse, Message
    from everstaff.nulls import InMemoryStore

    # Fully completed turn: assistant calls a tool, tool result follows
    history = [
        Message(role="user", content="do something"),
        Message(role="assistant", content=None,
                tool_calls=[{"id": "tc-done", "name": "some_tool", "arguments": "{}"}]),
        Message(role="tool", tool_call_id="tc-done", content="tool result"),
        Message(role="assistant", content="all done"),
    ]

    mem = InMemoryStore()
    await mem.save("sess-complete", history)

    received_messages = []

    async def fake_complete(messages, tools, system=None):
        received_messages.extend(messages)
        return LLMResponse(content="ok", tool_calls=[])

    llm = MagicMock()
    llm.complete_stream = None  # prevent AsyncMock auto-attribute from triggering streaming path
    llm.complete = AsyncMock(side_effect=fake_complete)
    llm.model_id = "gpt-4"

    ctx = _make_ctx(memory=mem)
    ctx.session_id = "sess-complete"
    runtime = AgentRuntime(context=ctx, llm_client=llm)

    await runtime.run("follow-up")

    # The completed tool_call turn must still be present
    assistant_with_tc = [m for m in received_messages if m.role == "assistant" and m.tool_calls]
    assert assistant_with_tc, "Completed assistant+tool_calls turn was incorrectly truncated"


@pytest.mark.asyncio
async def test_stats_accumulate_across_hitl_resumes():
    """Stats (tool_calls_count, own_calls) must accumulate across HITL resume cycles.

    When a session is paused for HITL and then resumed, the new run() call must
    load the existing saved stats and continue accumulating from them, not start fresh.
    Otherwise tool_calls_count resets to 0 on each resume.
    """
    from everstaff.core.runtime import AgentRuntime
    from everstaff.protocols import LLMResponse, HumanApprovalRequired, HitlRequest
    from everstaff.memory.file_store import FileMemoryStore
    from everstaff.storage.local import LocalFileStore
    import tempfile, os

    hitl_req = HitlRequest(
        hitl_id="test-hitl-acc",
        type="approve_reject",
        prompt="Approve?",
    )

    call_count = 0
    async def fake_complete(messages, tools, system=None):
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            # First two LLM calls trigger HITL
            tc = ToolCallRequest(id=f"tc{call_count}", name="request_human_input",
                                 args={"type": "approve_reject", "prompt": "Approve?"})
            return LLMResponse(content=f"Turn {call_count}", tool_calls=[tc])
        return LLMResponse(content="done", tool_calls=[])

    llm = MagicMock()
    llm.complete_stream = None  # prevent AsyncMock auto-attribute from triggering streaming path
    llm.complete = AsyncMock(side_effect=fake_complete)
    llm.model_id = "test-model"

    with tempfile.TemporaryDirectory() as tmpdir:
        store = LocalFileStore(tmpdir)
        mem = FileMemoryStore(base_dir=tmpdir)
        ctx = _make_ctx(memory=mem)

        # First run — pauses at HITL after tool_calls_count=1
        with pytest.raises(HumanApprovalRequired):
            with patch.object(ctx.tool_pipeline, "execute", side_effect=HumanApprovalRequired(hitl_req)):
                runtime = AgentRuntime(context=ctx, llm_client=llm)
                await runtime.run("start")

        # Check stats after first HITL
        import json
        session_file = os.path.join(tmpdir, ctx.session_id, "session.json")
        data1 = json.loads(open(session_file).read())
        tc1 = data1["metadata"]["tool_calls_count"]
        assert tc1 == 1, f"After first HITL, tool_calls_count should be 1, got {tc1}"

        # Second run (resume) — should accumulate stats, not reset
        call_count = 1  # reset so next complete() returns second HITL
        hitl_req2 = HitlRequest(hitl_id="test-hitl-acc-2", type="approve_reject", prompt="Approve 2?")
        with pytest.raises(HumanApprovalRequired):
            with patch.object(ctx.tool_pipeline, "execute", side_effect=HumanApprovalRequired(hitl_req2)):
                await runtime.run("resume decision")

        data2 = json.loads(open(session_file).read())
        tc2 = data2["metadata"]["tool_calls_count"]
        # Must be 2: one from first run + one from second run
        assert tc2 == 2, (
            f"After second HITL, tool_calls_count should be 2 (accumulated), got {tc2}. "
            f"Stats reset on resume instead of accumulating."
        )


@pytest.mark.asyncio
async def test_system_prompt_metadata_includes_injections():
    """The system_prompt saved in session metadata must be the FULL prompt
    (including sub-agent/skill/knowledge injections), not just the raw base instructions.

    This lets users inspect what was actually sent to the LLM.
    """
    from everstaff.core.runtime import AgentRuntime
    from everstaff.protocols import LLMResponse

    saved_system_prompts = []

    class CapturingMemory:
        async def load(self, sid): return []
        async def save(self, sid, msgs, **kw):
            if kw.get("system_prompt") is not None:
                saved_system_prompts.append(kw["system_prompt"])

    llm = MagicMock()
    llm.complete_stream = None  # prevent AsyncMock auto-attribute from triggering streaming path
    llm.complete = AsyncMock(return_value=LLMResponse(content="done", tool_calls=[]))
    llm.model_id = "test-model"

    # Build context with a sub-agent provider that produces an injection
    from everstaff.core.context import AgentContext
    from everstaff.tools.pipeline import ToolCallPipeline
    from everstaff.tools.stages import ExecutionStage
    from everstaff.tools.default_registry import DefaultToolRegistry
    from everstaff.nulls import NullTracer

    class FakeSubAgentProvider:
        def get_tools(self): return []
        def get_prompt_injection(self): return "## Available Sub-Agents\n\n- **worker**: does work"

    class FakeNullProvider:
        def get_tools(self): return []
        def get_prompt_injection(self): return ""

    reg = DefaultToolRegistry()
    pipeline = ToolCallPipeline([ExecutionStage(reg)])
    mem = CapturingMemory()
    ctx = AgentContext(
        tool_registry=reg,
        memory=mem,
        tool_pipeline=pipeline,
        tracer=NullTracer(),
        agent_name="test-agent",
        system_prompt="You are a team leader.",
        sub_agent_provider=FakeSubAgentProvider(),
        skill_provider=FakeNullProvider(),
        knowledge_provider=FakeNullProvider(),
        mcp_provider=FakeNullProvider(),
    )

    runtime = AgentRuntime(context=ctx, llm_client=llm)
    await runtime.run("hello")

    assert saved_system_prompts, "system_prompt was never saved"
    full_prompt = saved_system_prompts[-1]
    assert "## Available Sub-Agents" in full_prompt, (
        f"Saved system_prompt is missing sub-agent injection. Got: {full_prompt!r}"
    )
    assert "You are a team leader" in full_prompt, (
        f"Saved system_prompt is missing base instructions. Got: {full_prompt!r}"
    )


@pytest.mark.asyncio
async def test_run_preserves_llm_text_when_hitl_triggered():
    """When LLM emits text before calling request_human_input, runtime.run() must
    raise HumanApprovalRequired while saving the LLM's text in session messages."""
    from everstaff.core.runtime import AgentRuntime
    from everstaff.protocols import LLMResponse, HumanApprovalRequired, HitlRequest
    from everstaff.nulls import InMemoryStore

    # LLM says something, then calls request_human_input
    hitl_req = HitlRequest(
        hitl_id="test-hitl-preserve",
        type="approve_reject",
        prompt="Should I continue?",
    )

    call_count = 0
    async def fake_complete(messages, tools, system=None):
        nonlocal call_count
        call_count += 1
        return LLMResponse(
            content="好的，我需要您的确认才能继续。",
            tool_calls=[ToolCallRequest(
                id="tc-hitl",
                name="request_human_input",
                args={"type": "approve_reject", "prompt": "Should I continue?"},
            )],
        )

    llm = MagicMock()
    llm.complete_stream = None  # prevent AsyncMock auto-attribute from triggering streaming path
    llm.complete = AsyncMock(side_effect=fake_complete)
    llm.model_id = "gpt-4"

    mem = InMemoryStore()

    ctx = _make_ctx(memory=mem)
    # runtime.run() must raise HumanApprovalRequired
    with pytest.raises(HumanApprovalRequired) as exc_info:
        with patch.object(ctx.tool_pipeline, "execute", side_effect=HumanApprovalRequired(hitl_req)):
            runtime = AgentRuntime(context=ctx, llm_client=llm)
            await runtime.run("请帮我处理这件事")

    # The exception must carry the HITL request
    assert exc_info.value.requests[0].hitl_id == "test-hitl-preserve"

    # The LLM's text must be saved in session messages
    saved_messages = await mem.load(ctx.session_id)
    assistant_msgs = [m for m in saved_messages if m.role == "assistant"]
    assert any("好的，我需要您的确认才能继续" in (m.content or "") for m in assistant_msgs), (
        f"LLM text was not saved in session messages. Messages: {saved_messages}"
    )


@pytest.mark.asyncio
async def test_runtime_passes_max_tokens_to_memory_save(tmp_path):
    """AgentContext.max_tokens must be forwarded to every memory.save() call.

    This ensures session metadata always records the configured output limit,
    not just when it's set at build time.
    """
    import os, json
    from everstaff.core.runtime import AgentRuntime
    from everstaff.memory.file_store import FileMemoryStore
    from everstaff.protocols import LLMResponse

    store = FileMemoryStore(tmp_path)

    ctx = _make_ctx(memory=store)
    ctx.max_tokens = 1024  # type: ignore[attr-defined]

    llm = MagicMock()
    llm.complete_stream = None  # prevent AsyncMock auto-attribute from triggering streaming path
    llm.model_id = "gpt-4"
    llm.complete = AsyncMock(return_value=LLMResponse(content="done", tool_calls=[]))

    runtime = AgentRuntime(context=ctx, llm_client=llm)
    await runtime.run("hi")

    raw = json.loads((tmp_path / ctx.session_id / "session.json").read_text())
    saved = raw["metadata"].get("max_tokens")
    assert saved == 1024, (
        f"max_tokens not saved in metadata by runtime. Got: {saved!r}"
    )


@pytest.mark.asyncio
async def test_system_prompt_includes_hitl_rules_when_tool_registered():
    """When request_human_input is in the tool registry, its behavioral rules
    must appear in the system prompt built by runtime."""
    from everstaff.tools.hitl_tool import RequestHumanInputTool
    from everstaff.core.runtime import AgentRuntime
    from everstaff.tools.default_registry import DefaultToolRegistry
    from everstaff.nulls import InMemoryStore
    from everstaff.tools.pipeline import ToolCallPipeline
    from everstaff.tools.stages import ExecutionStage
    from everstaff.core.context import AgentContext

    hitl_tool = RequestHumanInputTool()
    registry = DefaultToolRegistry()
    registry.register_native(hitl_tool)

    ctx = AgentContext(
        tool_registry=registry,
        memory=InMemoryStore(),
        tool_pipeline=ToolCallPipeline([ExecutionStage(registry)]),
        system_prompt="You are a test agent.",
    )
    llm = MagicMock()
    llm.complete_stream = None  # prevent AsyncMock auto-attribute from triggering streaming path
    runtime = AgentRuntime(context=ctx, llm_client=llm)

    prompt = runtime._build_system_prompt()
    assert "Human Interaction Rules" in prompt
    assert "request_human_input" in prompt

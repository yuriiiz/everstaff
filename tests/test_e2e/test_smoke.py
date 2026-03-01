import pytest
from unittest.mock import AsyncMock, MagicMock
from everstaff.protocols import LLMResponse, Message


@pytest.mark.asyncio
async def test_full_agent_run_no_tools():
    """Full pipeline: AgentBuilder -> AgentRuntime -> LLM -> response."""
    from everstaff.builder.agent_builder import AgentBuilder
    from everstaff.builder.environment import TestEnvironment
    from everstaff.protocols import LLMResponse
    from everstaff.schema.agent_spec import AgentSpec
    import yaml

    spec = AgentSpec.model_validate(yaml.safe_load("""
        agent_name: smoke-agent
        instructions: You are a helpful assistant.
        tools: []
        skills: []
    """))

    env = TestEnvironment()
    runtime, ctx = await AgentBuilder(spec, env).build()

    runtime._llm.complete_stream = None  # prevent auto-attribute from triggering streaming path
    runtime._llm.complete = AsyncMock(
        return_value=LLMResponse(content="Smoke test passed!", tool_calls=[])
    )

    result = await runtime.run("Run the smoke test")
    assert result == "Smoke test passed!"


@pytest.mark.asyncio
async def test_full_agent_run_with_tool():
    """Pipeline with one tool call: LLM -> tool -> LLM -> final response."""
    from everstaff.protocols import LLMResponse, ToolCallRequest, ToolDefinition, ToolResult
    from everstaff.tools.default_registry import DefaultToolRegistry
    from everstaff.tools.pipeline import ToolCallPipeline
    from everstaff.tools.stages import ExecutionStage, PermissionStage
    from everstaff.core.context import AgentContext
    from everstaff.core.runtime import AgentRuntime
    from everstaff.nulls import AllowAllChecker, InMemoryStore

    class UpperTool:
        @property
        def definition(self):
            return ToolDefinition("upper", "uppercases text", {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            })
        async def execute(self, args):
            return ToolResult(tool_call_id="", content=args["text"].upper())

    reg = DefaultToolRegistry()
    reg.register(UpperTool())

    pipeline = ToolCallPipeline([
        PermissionStage(AllowAllChecker()),
        ExecutionStage(reg),
    ])
    ctx = AgentContext(
        tool_registry=reg,
        memory=InMemoryStore(),
        tool_pipeline=pipeline,
    )

    call_n = 0
    async def fake_complete(messages, tools, system=None):
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return LLMResponse(
                content=None,
                tool_calls=[ToolCallRequest(id="c1", name="upper", args={"text": "hello"})],
            )
        return LLMResponse(content="Result: HELLO", tool_calls=[])

    llm = MagicMock()
    llm.complete_stream = None  # prevent auto-attribute from triggering streaming path
    llm.complete = AsyncMock(side_effect=fake_complete)

    runtime = AgentRuntime(context=ctx, llm_client=llm)
    result = await runtime.run("uppercase hello")
    assert result == "Result: HELLO"
    assert call_n == 2

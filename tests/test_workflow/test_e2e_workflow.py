import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from everstaff.protocols import LLMResponse, CancellationEvent, ToolCallRequest


@pytest.mark.asyncio
async def test_workflow_runs_via_agent_runtime():
    """Full path: AgentRuntime → write_workflow_plan tool → DAGEngine → sub-agents."""
    from everstaff.builder.agent_builder import AgentBuilder
    from everstaff.builder.environment import TestEnvironment
    from everstaff.schema.agent_spec import AgentSpec, SubAgentSpec

    spec = AgentSpec(
        agent_name="coordinator",
        instructions="You coordinate workflows.",
        workflow={"max_parallel": 2},
        sub_agents={
            "writer": SubAgentSpec(name="writer", description="writes text"),
            "reviewer": SubAgentSpec(name="reviewer", description="reviews text"),
        },
    )
    env = TestEnvironment()

    # Main coordinator LLM: first turn calls write_workflow_plan, second turn summarizes
    coordinator_llm = MagicMock()
    coordinator_llm.complete_stream = None  # prevent MagicMock auto-attribute from triggering streaming path
    coordinator_llm.complete = AsyncMock(side_effect=[
        LLMResponse(content=None, tool_calls=[
            ToolCallRequest(id="tc1", name="write_workflow_plan", args={
                "goal": "write and review a doc",
                "title": "Doc Workflow",
                "tasks": [
                    {"task_id": "t1", "title": "Write", "description": "write doc",
                     "assigned_agent": "writer", "dependencies": []},
                    {"task_id": "t2", "title": "Review", "description": "review doc",
                     "assigned_agent": "reviewer", "dependencies": ["t1"]},
                ],
            }),
        ]),
        LLMResponse(content="Workflow complete! The doc was written and reviewed.", tool_calls=[]),
    ])

    # Child agent LLMs: writer and reviewer each return simple responses
    child_llm = MagicMock()
    child_llm.complete_stream = None  # prevent MagicMock auto-attribute from triggering streaming path
    child_llm.complete = AsyncMock(return_value=LLMResponse(
        content="Child agent task completed.", tool_calls=[]
    ))

    with patch.object(env, "build_llm_client", side_effect=[coordinator_llm, child_llm, child_llm]):
        runtime, ctx = await AgentBuilder(spec, env).build()
        result = await runtime.run("Please write and review a document.")

    assert "Workflow complete" in result
    # Both sub-agent LLMs were called
    assert child_llm.complete.call_count == 2


@pytest.mark.asyncio
async def test_workflow_stops_on_cancellation():
    """CancellationEvent propagates from parent session to DAGEngine."""
    from everstaff.builder.agent_builder import AgentBuilder
    from everstaff.builder.environment import TestEnvironment
    from everstaff.schema.agent_spec import AgentSpec, SubAgentSpec
    import asyncio

    spec = AgentSpec(
        agent_name="coordinator",
        instructions="coordinate",
        workflow={"max_parallel": 2},
        sub_agents={"worker": SubAgentSpec(name="worker", description="works")},
    )
    env = TestEnvironment()
    cancellation = CancellationEvent()

    coordinator_llm = MagicMock()
    coordinator_llm.complete_stream = None  # prevent MagicMock auto-attribute from triggering streaming path
    coordinator_llm.complete = AsyncMock(return_value=LLMResponse(
        content=None, tool_calls=[
            ToolCallRequest(id="tc1", name="write_workflow_plan", args={
                "goal": "do stuff", "title": "W",
                "tasks": [{"task_id": "t1", "title": "T", "description": "d",
                           "assigned_agent": "worker", "dependencies": []}],
            }),
        ]
    ))

    async def slow_worker(*a, **kw):
        await asyncio.sleep(10)  # will be cancelled
        return LLMResponse(content="done", tool_calls=[])

    child_llm = MagicMock()
    child_llm.complete_stream = None  # prevent MagicMock auto-attribute from triggering streaming path
    child_llm.complete = AsyncMock(side_effect=slow_worker)

    # Cancel after short delay
    async def cancel_soon():
        await asyncio.sleep(0.1)
        cancellation.cancel()

    with patch.object(env, "build_llm_client", side_effect=[coordinator_llm, child_llm]):
        runtime, ctx = await AgentBuilder(spec, env, parent_cancellation=cancellation).build()
        asyncio.create_task(cancel_soon())
        result = await runtime.run("do stuff")

    assert "[Stopped]" in result or "stopped" in result.lower()

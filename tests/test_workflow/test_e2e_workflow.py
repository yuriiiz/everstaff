import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from everstaff.protocols import LLMResponse, CancellationEvent, ToolCallRequest


@pytest.mark.asyncio
async def test_workflow_runs_via_agent_runtime():
    """Full path: AgentRuntime -> write_plan + execute_plan_step tools -> DAGEngine -> sub-agents."""
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

    plan_id_holder = {}

    def coordinator_side_effect(*args, **kwargs):
        messages = args[0] if args else kwargs.get("messages", [])

        # Inspect messages to determine what stage we're at
        for msg in reversed(messages):
            role = getattr(msg, "role", "")
            content = str(getattr(msg, "content", "") or "")

            if role == "tool" and "plan_id:" in content:
                # Extract plan_id from the write_plan tool result
                for line in content.split("\n"):
                    if line.startswith("plan_id:"):
                        plan_id_holder["id"] = line.split(":", 1)[1].strip()
                        break

            # If we got an execute_plan_step result showing plan completed, summarize
            if role == "tool" and "Plan completed" in content:
                return LLMResponse(
                    content="Workflow complete! The doc was written and reviewed.",
                    tool_calls=[],
                )

            # If we got an execute_plan_step result but plan not done, call again
            if role == "tool" and "Plan Progress" in content and "Plan completed" not in content:
                pid = plan_id_holder.get("id", "unknown")
                return LLMResponse(content=None, tool_calls=[
                    ToolCallRequest(id="tc3", name="execute_plan_step", args={"plan_id": pid}),
                ])

        # If we have a plan_id from write_plan, call execute_plan_step
        if "id" in plan_id_holder:
            pid = plan_id_holder["id"]
            return LLMResponse(content=None, tool_calls=[
                ToolCallRequest(id="tc2", name="execute_plan_step", args={"plan_id": pid}),
            ])

        # First call: create the plan
        return LLMResponse(content=None, tool_calls=[
            ToolCallRequest(id="tc1", name="write_plan", args={
                "goal": "write and review a doc",
                "title": "Doc Workflow",
                "tasks": [
                    {"task_id": "t1", "title": "Write", "description": "write doc",
                     "assigned_agent": "writer", "dependencies": []},
                    {"task_id": "t2", "title": "Review", "description": "review doc",
                     "assigned_agent": "reviewer", "dependencies": ["t1"]},
                ],
            }),
        ])

    coordinator_llm = MagicMock()
    coordinator_llm.complete_stream = None
    coordinator_llm.complete = AsyncMock(side_effect=coordinator_side_effect)

    # Child agent LLMs: writer and reviewer each return simple responses
    child_llm = MagicMock()
    child_llm.complete_stream = None
    child_llm.complete = AsyncMock(return_value=LLMResponse(
        content="Child agent task completed.", tool_calls=[]
    ))

    with patch.object(env, "build_llm_client", side_effect=[coordinator_llm, child_llm, child_llm]):
        runtime, ctx = await AgentBuilder(spec, env).build()
        result = await runtime.run("Please write and review a document.")

    assert "Workflow complete" in result
    # Both sub-agent LLMs were called (writer + reviewer)
    assert child_llm.complete.call_count == 2


@pytest.mark.asyncio
async def test_workflow_stops_on_cancellation():
    """CancellationEvent propagates from parent session to DAGEngine via execute_plan_step."""
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

    plan_id_holder = {}

    def coordinator_side_effect(*args, **kwargs):
        messages = args[0] if args else kwargs.get("messages", [])

        for msg in reversed(messages):
            role = getattr(msg, "role", "")
            content = str(getattr(msg, "content", "") or "")
            if role == "tool" and "plan_id:" in content:
                for line in content.split("\n"):
                    if line.startswith("plan_id:"):
                        plan_id_holder["id"] = line.split(":", 1)[1].strip()
                        break

        if "id" in plan_id_holder:
            pid = plan_id_holder["id"]
            return LLMResponse(content=None, tool_calls=[
                ToolCallRequest(id="tc2", name="execute_plan_step", args={"plan_id": pid}),
            ])

        return LLMResponse(content=None, tool_calls=[
            ToolCallRequest(id="tc1", name="write_plan", args={
                "goal": "do stuff", "title": "W",
                "tasks": [{"task_id": "t1", "title": "T", "description": "d",
                           "assigned_agent": "worker", "dependencies": []}],
            }),
        ])

    coordinator_llm = MagicMock()
    coordinator_llm.complete_stream = None
    coordinator_llm.complete = AsyncMock(side_effect=coordinator_side_effect)

    async def slow_worker(*a, **kw):
        await asyncio.sleep(10)  # will be cancelled
        return LLMResponse(content="done", tool_calls=[])

    child_llm = MagicMock()
    child_llm.complete_stream = None
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

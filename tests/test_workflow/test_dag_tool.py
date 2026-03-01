import pytest
from unittest.mock import MagicMock, AsyncMock
from everstaff.protocols import CancellationEvent


def make_factory(response: str = "task done", agents: dict | None = None) -> MagicMock:
    factory = MagicMock()
    factory.run = AsyncMock(return_value=response)
    factory._agents = agents if agents is not None else {}
    return factory


@pytest.mark.asyncio
async def test_dag_tool_returns_summary():
    from everstaff.workflow.dag_tool import DAGTool

    tool = DAGTool(
        factory=make_factory("result", agents={"worker": MagicMock()}),
        max_parallel=2,
        cancellation=CancellationEvent(),
        tracer=None,
        session_id="sess-1",
    )
    result = await tool.execute({
        "goal": "build something",
        "title": "Test Workflow",
        "tasks": [{
            "task_id": "t1",
            "title": "Do it",
            "description": "do the thing",
            "assigned_agent": "worker",
            "dependencies": [],
        }],
    })
    assert not result.is_error
    assert "t1" in result.content or "completed" in result.content.lower()


@pytest.mark.asyncio
async def test_dag_tool_emits_workflow_start_end():
    from everstaff.workflow.dag_tool import DAGTool

    events: list = []

    class SpyTracer:
        def on_event(self, e):
            events.append(e.kind)

    tool = DAGTool(
        factory=make_factory("ok", agents={"a": MagicMock()}),
        max_parallel=2,
        cancellation=CancellationEvent(),
        tracer=SpyTracer(),
        session_id="sess-1",
    )
    await tool.execute({
        "goal": "g", "title": "t",
        "tasks": [{"task_id": "t1", "title": "T", "description": "d",
                   "assigned_agent": "a", "dependencies": []}],
    })
    assert "workflow_start" in events
    assert "workflow_end" in events


@pytest.mark.asyncio
async def test_agent_builder_registers_dag_tool_when_workflow_set():
    """AgentBuilder registers write_workflow_plan tool when spec.workflow is set."""
    from everstaff.builder.agent_builder import AgentBuilder
    from everstaff.builder.environment import TestEnvironment
    from everstaff.schema.agent_spec import AgentSpec

    spec = AgentSpec(
        agent_name="coordinator",
        instructions="coordinate",
        workflow={"max_parallel": 3},
    )
    env = TestEnvironment()
    _, ctx = await AgentBuilder(spec, env).build()

    tool_names = [t.name for t in ctx.tool_registry.get_definitions()]
    assert "write_workflow_plan" in tool_names


@pytest.mark.asyncio
async def test_agent_builder_no_dag_tool_without_workflow():
    from everstaff.builder.agent_builder import AgentBuilder
    from everstaff.builder.environment import TestEnvironment
    from everstaff.schema.agent_spec import AgentSpec

    spec = AgentSpec(agent_name="simple", instructions="do stuff")
    env = TestEnvironment()
    _, ctx = await AgentBuilder(spec, env).build()

    tool_names = [t.name for t in ctx.tool_registry.get_definitions()]
    assert "write_workflow_plan" not in tool_names


@pytest.mark.asyncio
async def test_dag_tool_rejects_unknown_assigned_agent():
    """execute() must return an error ToolResult immediately if any task references
    an agent name not in the factory's available_agents."""
    from everstaff.workflow.dag_tool import DAGTool
    from unittest.mock import MagicMock

    factory = MagicMock()
    factory._agents = {"agent_a": MagicMock()}  # only agent_a is valid

    tool = DAGTool(
        factory=factory,
        max_parallel=2,
        cancellation=MagicMock(is_cancelled=False),
        tracer=None,
        session_id="test-session",
    )

    result = await tool.execute({
        "goal": "do stuff",
        "title": "test plan",
        "tasks": [
            {
                "task_id": "t1",
                "title": "valid task",
                "description": "uses agent_a",
                "assigned_agent": "agent_a",
                "dependencies": [],
            },
            {
                "task_id": "t2",
                "title": "bad task",
                "description": "uses nonexistent agent",
                "assigned_agent": "agent_xyz",
                "dependencies": [],
            },
        ],
    })

    assert result.is_error
    assert "agent_xyz" in result.content
    assert "unknown" in result.content.lower() or "not found" in result.content.lower()


@pytest.mark.asyncio
async def test_dag_tool_returns_child_stats_from_sub_agents():
    """DAGTool.execute() must return child_stats aggregating all sub-agent token usage.

    When workflow tasks run sub-agents, each sub-agent has its own SessionStats.
    The parent agent must receive these as children_calls so the overall session
    metadata shows correct token usage across all sub-agents.
    """
    from everstaff.workflow.dag_tool import DAGTool
    from everstaff.schema.token_stats import SessionStats, TokenUsage

    # Build a factory that returns child stats alongside the output
    child_stats_1 = SessionStats()
    child_stats_1.record(TokenUsage(input_tokens=50, output_tokens=20, total_tokens=70, model_id="gpt-4"))
    child_stats_2 = SessionStats()
    child_stats_2.record(TokenUsage(input_tokens=30, output_tokens=10, total_tokens=40, model_id="gpt-4"))

    stats_by_agent = {"agent_a": child_stats_1, "agent_b": child_stats_2}
    call_order = []

    async def mock_run_with_stats(agent_name, prompt):
        call_order.append(agent_name)
        return "done", stats_by_agent.get(agent_name)

    factory = MagicMock()
    factory._agents = {"agent_a": MagicMock(), "agent_b": MagicMock()}
    factory.run_with_stats = AsyncMock(side_effect=mock_run_with_stats)
    # Also provide run() for fallback compatibility
    factory.run = AsyncMock(return_value="done")

    tool = DAGTool(
        factory=factory,
        max_parallel=2,
        cancellation=CancellationEvent(),
        tracer=None,
        session_id="sess-stats",
    )
    result = await tool.execute({
        "goal": "multi-agent task",
        "title": "Stats Test",
        "tasks": [
            {"task_id": "t1", "title": "Task A", "description": "run a",
             "assigned_agent": "agent_a", "dependencies": []},
            {"task_id": "t2", "title": "Task B", "description": "run b",
             "assigned_agent": "agent_b", "dependencies": []},
        ],
    })

    assert not result.is_error
    assert result.child_stats is not None, "child_stats must not be None — workflow ran sub-agents"
    merged: SessionStats = result.child_stats
    total_input = sum(c.input_tokens for c in merged.own_calls)
    assert total_input == 80, (
        f"Expected total input_tokens=80 (50+30) from both sub-agents, got {total_input}. "
        f"children_calls={merged.own_calls}"
    )

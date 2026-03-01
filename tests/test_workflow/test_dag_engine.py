"""Tests for DAGEngine using WorkflowSubAgentFactory + CancellationEvent."""
import pytest
from unittest.mock import AsyncMock


def make_plan(tasks: list[dict]):
    from everstaff.schema.workflow_spec import PlanSpec, TaskNodeSpec
    return PlanSpec(
        goal="test goal",
        title="Test Workflow",
        tasks=[TaskNodeSpec(**t) for t in tasks],
        status="approved",
    )


def make_factory(responses: dict):
    """Stub factory that returns preset responses by agent name."""
    from unittest.mock import MagicMock
    factory = MagicMock()
    async def run(agent_name: str, prompt: str) -> str:
        return responses.get(agent_name, f"result from {agent_name}")
    factory.run = run
    return factory


@pytest.mark.asyncio
async def test_dag_engine_runs_single_task():
    from everstaff.workflow.dag_engine import DAGEngine
    from everstaff.schema.workflow_spec import TaskStatus
    from everstaff.protocols import CancellationEvent

    plan = make_plan([{
        "task_id": "t1", "title": "Task 1", "description": "do something",
        "assigned_agent": "worker", "dependencies": [],
    }])
    factory = make_factory({"worker": "task 1 done"})
    engine = DAGEngine(
        plan=plan,
        factory=factory,
        cancellation=CancellationEvent(),
    )
    results = await engine.execute()

    assert "t1" in results
    assert results["t1"].status == TaskStatus.COMPLETED
    assert results["t1"].output == "task 1 done"


@pytest.mark.asyncio
async def test_dag_engine_respects_dependencies():
    from everstaff.workflow.dag_engine import DAGEngine
    from everstaff.schema.workflow_spec import TaskStatus
    from everstaff.protocols import CancellationEvent

    order: list = []
    async def run(agent_name: str, prompt: str) -> str:
        order.append(agent_name)
        return f"{agent_name} done"

    from unittest.mock import MagicMock
    factory = MagicMock()
    factory.run = run

    plan = make_plan([
        {"task_id": "t1", "title": "First",  "description": "step 1",
         "assigned_agent": "agent_a", "dependencies": []},
        {"task_id": "t2", "title": "Second", "description": "step 2",
         "assigned_agent": "agent_b", "dependencies": ["t1"]},
    ])
    engine = DAGEngine(plan=plan, factory=factory, cancellation=CancellationEvent())
    results = await engine.execute()

    assert order.index("agent_a") < order.index("agent_b")
    assert results["t1"].status == TaskStatus.COMPLETED
    assert results["t2"].status == TaskStatus.COMPLETED


@pytest.mark.asyncio
async def test_dag_engine_stops_on_cancellation():
    from everstaff.workflow.dag_engine import DAGEngine
    from everstaff.schema.workflow_spec import TaskStatus
    from everstaff.protocols import CancellationEvent

    cancellation = CancellationEvent()
    cancellation.cancel()  # pre-cancelled

    plan = make_plan([{
        "task_id": "t1", "title": "Task", "description": "...",
        "assigned_agent": "worker", "dependencies": [],
    }])
    factory = make_factory({"worker": "should not run"})
    engine = DAGEngine(plan=plan, factory=factory, cancellation=cancellation)
    results = await engine.execute()

    # All tasks skipped
    assert all(r.status == TaskStatus.SKIPPED for r in results.values())


@pytest.mark.asyncio
async def test_dag_engine_emits_task_trace_events():
    from everstaff.workflow.dag_engine import DAGEngine
    from everstaff.protocols import CancellationEvent

    events: list = []

    class SpyTracer:
        def on_event(self, e):
            events.append(e.kind)

    plan = make_plan([{
        "task_id": "t1", "title": "Task", "description": "...",
        "assigned_agent": "worker", "dependencies": [],
    }])
    factory = make_factory({"worker": "done"})
    engine = DAGEngine(
        plan=plan, factory=factory,
        cancellation=CancellationEvent(),
        tracer=SpyTracer(), session_id="sess-1",
    )
    await engine.execute()

    assert "workflow_task_start" in events
    assert "workflow_task_end" in events


@pytest.mark.asyncio
async def test_empty_assigned_agent_falls_back_to_coordinator():
    """When assigned_agent is empty string, coordinator executes the task."""
    from everstaff.workflow.dag_engine import DAGEngine
    from everstaff.schema.workflow_spec import TaskStatus
    from everstaff.protocols import CancellationEvent
    from unittest.mock import MagicMock

    called_with = []

    async def run(agent_name: str, prompt: str) -> str:
        called_with.append(agent_name)
        return "done"

    factory = MagicMock()
    factory.run = run

    plan = make_plan([{
        "task_id": "t1", "title": "Task 1", "description": "do something",
        "assigned_agent": "",  # empty!
        "dependencies": [],
    }])

    engine = DAGEngine(
        plan=plan,
        factory=factory,
        cancellation=CancellationEvent(),
        coordinator_name="MyCoordinator",
    )
    results = await engine.execute()

    assert results["t1"].status == TaskStatus.COMPLETED
    assert called_with == ["MyCoordinator"]  # fell back to coordinator


@pytest.mark.asyncio
async def test_empty_assigned_agent_no_coordinator_produces_message():
    """When both assigned_agent and coordinator_name are empty, task completes with a message (no factory call)."""
    from everstaff.workflow.dag_engine import DAGEngine
    from everstaff.schema.workflow_spec import TaskStatus
    from everstaff.protocols import CancellationEvent
    from unittest.mock import MagicMock

    factory = MagicMock()
    factory.run = MagicMock()  # should NOT be called

    plan = make_plan([{
        "task_id": "t1", "title": "Task 1", "description": "do something",
        "assigned_agent": "",
        "dependencies": [],
    }])

    engine = DAGEngine(
        plan=plan,
        factory=factory,
        cancellation=CancellationEvent(),
        coordinator_name="",  # also empty
    )
    results = await engine.execute()

    assert results["t1"].status == TaskStatus.COMPLETED
    factory.run.assert_not_called()
    assert "no coordinator" in results["t1"].output.lower()


"""Tests for DAGEngine.execute_step() — single-round DAG execution."""
import pytest
from unittest.mock import MagicMock, AsyncMock


def make_plan(tasks, status="executing"):
    from everstaff.schema.workflow_spec import PlanSpec, TaskNodeSpec
    return PlanSpec(
        goal="test goal", title="Test",
        tasks=[TaskNodeSpec(**t) for t in tasks], status=status,
    )


@pytest.mark.asyncio
async def test_execute_step_runs_ready_tasks():
    """execute_step runs all ready tasks (deps met) in one round."""
    from everstaff.workflow.dag_engine import DAGEngine
    from everstaff.protocols import CancellationEvent

    factory = MagicMock()
    factory.run = AsyncMock(return_value="done")

    plan = make_plan([
        {"task_id": "t1", "title": "A", "description": "a", "assigned_agent": "w", "dependencies": []},
        {"task_id": "t2", "title": "B", "description": "b", "assigned_agent": "w", "dependencies": []},
        {"task_id": "t3", "title": "C", "description": "c", "assigned_agent": "w", "dependencies": ["t1", "t2"]},
    ])

    engine = DAGEngine(plan=plan, factory=factory, cancellation=CancellationEvent(), max_parallel=5)
    step_result = await engine.execute_step()

    assert step_result.completed_tasks == {"t1", "t2"}
    assert step_result.pending_tasks == {"t3"}
    assert not step_result.is_plan_done


@pytest.mark.asyncio
async def test_execute_step_second_round_after_seed():
    """execute_step picks up t3 after t1,t2 are seeded as completed."""
    from everstaff.workflow.dag_engine import DAGEngine
    from everstaff.schema.workflow_spec import TaskStatus, TaskResult
    from everstaff.protocols import CancellationEvent

    factory = MagicMock()
    factory.run = AsyncMock(return_value="final result")

    plan = make_plan([
        {"task_id": "t1", "title": "A", "description": "a", "assigned_agent": "w", "dependencies": []},
        {"task_id": "t2", "title": "B", "description": "b", "assigned_agent": "w", "dependencies": []},
        {"task_id": "t3", "title": "C", "description": "c", "assigned_agent": "w", "dependencies": ["t1", "t2"]},
    ])

    engine = DAGEngine(plan=plan, factory=factory, cancellation=CancellationEvent(), max_parallel=5)
    engine.seed_completed_results({
        "t1": TaskResult(task_id="t1", status=TaskStatus.COMPLETED, output="a done"),
        "t2": TaskResult(task_id="t2", status=TaskStatus.COMPLETED, output="b done"),
    })

    step_result = await engine.execute_step()
    assert step_result.completed_tasks == {"t3"}
    assert step_result.is_plan_done


@pytest.mark.asyncio
async def test_execute_step_no_ready_tasks_plan_done():
    from everstaff.workflow.dag_engine import DAGEngine
    from everstaff.schema.workflow_spec import TaskStatus, TaskResult
    from everstaff.protocols import CancellationEvent

    factory = MagicMock()
    plan = make_plan([
        {"task_id": "t1", "title": "A", "description": "a", "assigned_agent": "w", "dependencies": []},
    ])

    engine = DAGEngine(plan=plan, factory=factory, cancellation=CancellationEvent())
    engine.seed_completed_results({
        "t1": TaskResult(task_id="t1", status=TaskStatus.COMPLETED, output="done"),
    })

    step_result = await engine.execute_step()
    assert step_result.is_plan_done
    assert len(step_result.completed_tasks) == 0


@pytest.mark.asyncio
async def test_execute_step_respects_max_parallel():
    from everstaff.workflow.dag_engine import DAGEngine
    from everstaff.protocols import CancellationEvent

    call_counts = []
    async def mock_run(agent_name, prompt):
        call_counts.append(1)
        return "done"

    factory = MagicMock()
    factory.run = mock_run

    plan = make_plan([
        {"task_id": f"t{i}", "title": f"T{i}", "description": "d",
         "assigned_agent": "w", "dependencies": []}
        for i in range(4)
    ])

    engine = DAGEngine(plan=plan, factory=factory, cancellation=CancellationEvent(), max_parallel=2)
    step_result = await engine.execute_step()

    assert len(step_result.completed_tasks) == 4
    assert step_result.is_plan_done


@pytest.mark.asyncio
async def test_execute_step_returns_child_stats():
    from everstaff.workflow.dag_engine import DAGEngine
    from everstaff.schema.token_stats import SessionStats, TokenUsage
    from everstaff.protocols import CancellationEvent

    child_stats = SessionStats()
    child_stats.record(TokenUsage(input_tokens=50, output_tokens=20, total_tokens=70, model_id="m"))

    async def mock_run_with_stats(agent_name, prompt):
        return "done", child_stats

    factory = MagicMock()
    factory.run_with_stats = AsyncMock(side_effect=mock_run_with_stats)

    plan = make_plan([
        {"task_id": "t1", "title": "T", "description": "d", "assigned_agent": "w", "dependencies": []},
    ])

    engine = DAGEngine(plan=plan, factory=factory, cancellation=CancellationEvent())
    step_result = await engine.execute_step()
    assert step_result.child_stats is not None

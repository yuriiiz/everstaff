import pytest
from unittest.mock import AsyncMock, MagicMock
from everstaff.schema.workflow_spec import PlanSpec, TaskNodeSpec, TaskResult, TaskStatus


@pytest.mark.asyncio
async def test_dag_engine_calls_save_workflow_on_task_complete():
    """DAGEngine calls store.save_workflow() after task completes."""
    from everstaff.workflow.dag_engine import DAGEngine
    from everstaff.protocols import CancellationEvent

    plan = PlanSpec(
        plan_id="p1", title="T", goal="G",
        tasks=[TaskNodeSpec(task_id="t1", title="T1", description="d",
                            dependencies=[], assigned_agent="a1")],
    )

    mock_factory = MagicMock()
    mock_factory._agents = {"a1": MagicMock()}
    mock_factory.run_with_stats = AsyncMock(
        return_value=("done", MagicMock(own_calls=[], children_calls=[],
                                        tool_calls_count=0, errors_count=0))
    )

    mock_store = AsyncMock()
    mock_store.save_workflow = AsyncMock()

    engine = DAGEngine(
        plan=plan,
        factory=mock_factory,
        cancellation=CancellationEvent(),
        session_id="sess-1",
        memory=mock_store,
    )
    await engine.execute()

    assert mock_store.save_workflow.call_count >= 1
    # Verify session_id is passed correctly
    first_call = mock_store.save_workflow.call_args_list[0]
    assert first_call[0][0] == "sess-1"


@pytest.mark.asyncio
async def test_dag_engine_final_status_completed():
    """After execute(), the last persisted workflow has status 'completed'."""
    from everstaff.workflow.dag_engine import DAGEngine
    from everstaff.schema.workflow_spec import WorkflowRecord
    from everstaff.protocols import CancellationEvent

    plan = PlanSpec(
        plan_id="p2", title="T", goal="G",
        tasks=[TaskNodeSpec(task_id="t1", title="T1", description="d",
                            dependencies=[], assigned_agent="a1")],
    )

    mock_factory = MagicMock()
    mock_factory._agents = {"a1": MagicMock()}
    mock_factory.run_with_stats = AsyncMock(
        return_value=("output", MagicMock(own_calls=[], children_calls=[],
                                          tool_calls_count=0, errors_count=0))
    )

    saved_records = []

    async def capture_save(session_id, record):
        saved_records.append(record)

    mock_store = AsyncMock()
    mock_store.save_workflow = capture_save

    engine = DAGEngine(
        plan=plan,
        factory=mock_factory,
        cancellation=CancellationEvent(),
        session_id="sess-2",
        memory=mock_store,
    )
    await engine.execute()

    assert len(saved_records) >= 1
    assert saved_records[-1].status == "completed"
    assert "t1" in saved_records[-1].results
    assert saved_records[-1].results["t1"].status == TaskStatus.COMPLETED


@pytest.mark.asyncio
async def test_dag_engine_no_memory_doesnt_crash():
    """DAGEngine works fine when memory=None (no persistence)."""
    from everstaff.workflow.dag_engine import DAGEngine
    from everstaff.protocols import CancellationEvent

    plan = PlanSpec(
        plan_id="p3", title="T", goal="G",
        tasks=[TaskNodeSpec(task_id="t1", title="T1", description="d",
                            dependencies=[], assigned_agent="a1")],
    )

    mock_factory = MagicMock()
    mock_factory._agents = {"a1": MagicMock()}
    mock_factory.run_with_stats = AsyncMock(
        return_value=("ok", MagicMock(own_calls=[], children_calls=[],
                                       tool_calls_count=0, errors_count=0))
    )

    engine = DAGEngine(
        plan=plan,
        factory=mock_factory,
        cancellation=CancellationEvent(),
        session_id="sess-3",
        memory=None,  # No persistence
    )
    results = await engine.execute()
    assert results["t1"].status == TaskStatus.COMPLETED

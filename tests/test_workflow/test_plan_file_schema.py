# everstaff/tests/test_workflow/test_plan_file_schema.py
import pytest
from datetime import datetime


def test_plan_file_task_from_spec_and_result():
    from everstaff.schema.workflow_spec import PlanFileTask, TaskStatus
    task = PlanFileTask(
        task_id="t1", title="Test Task", description="do something",
        assigned_agent="worker", dependencies=["t0"],
        acceptance_criteria="must return data", max_retries=2,
        timeout_seconds=300, requires_evaluation=False,
        status=TaskStatus.COMPLETED, output="result data",
        retries=1, started_at=datetime(2026, 3, 11, 10, 0, 0),
        completed_at=datetime(2026, 3, 11, 10, 1, 0),
    )
    assert task.task_id == "t1"
    assert task.status == TaskStatus.COMPLETED
    assert task.output == "result data"
    assert task.retries == 1


def test_plan_file_task_defaults():
    from everstaff.schema.workflow_spec import PlanFileTask, TaskStatus
    task = PlanFileTask(task_id="t1", title="Test", description="desc")
    assert task.status == TaskStatus.PENDING
    assert task.output == ""
    assert task.retries == 0
    assert task.started_at is None
    assert task.completed_at is None
    assert task.assigned_agent is None
    assert task.dependencies == []


def test_plan_spec_has_updated_at_and_max_parallel():
    from everstaff.schema.workflow_spec import PlanSpec
    plan = PlanSpec(title="test", goal="goal", max_parallel=10)
    assert plan.max_parallel == 10
    assert plan.updated_at is not None


def test_plan_spec_to_yaml_roundtrip(tmp_path):
    from everstaff.schema.workflow_spec import PlanSpec, PlanFileTask, TaskStatus
    plan = PlanSpec(
        title="Test Plan", goal="test goal", max_parallel=5, status="draft",
        file_tasks=[
            PlanFileTask(task_id="t1", title="Task 1", description="do it",
                        assigned_agent="worker", dependencies=[], status=TaskStatus.PENDING),
            PlanFileTask(task_id="t2", title="Task 2", description="then this",
                        assigned_agent="worker", dependencies=["t1"], status=TaskStatus.PENDING),
        ],
    )
    path = tmp_path / "plan.yaml"
    plan.save_yaml(path)
    loaded = PlanSpec.load_yaml(path)
    assert loaded.title == "Test Plan"
    assert loaded.max_parallel == 5
    assert len(loaded.file_tasks) == 2
    assert loaded.file_tasks[0].task_id == "t1"
    assert loaded.file_tasks[1].dependencies == ["t1"]


def test_plan_spec_to_yaml_preserves_runtime_state(tmp_path):
    from everstaff.schema.workflow_spec import PlanSpec, PlanFileTask, TaskStatus
    plan = PlanSpec(
        title="Test", goal="test", max_parallel=3, status="executing",
        file_tasks=[
            PlanFileTask(task_id="t1", title="Done Task", description="was done",
                        status=TaskStatus.COMPLETED, output="result here",
                        retries=1, started_at=datetime(2026, 3, 11, 10, 0, 0),
                        completed_at=datetime(2026, 3, 11, 10, 1, 0)),
        ],
    )
    path = tmp_path / "plan.yaml"
    plan.save_yaml(path)
    loaded = PlanSpec.load_yaml(path)
    t = loaded.file_tasks[0]
    assert t.status == TaskStatus.COMPLETED
    assert t.output == "result here"
    assert t.retries == 1


def test_plan_file_task_to_task_node_spec():
    from everstaff.schema.workflow_spec import PlanFileTask, TaskStatus
    ft = PlanFileTask(task_id="t1", title="T", description="d",
                      assigned_agent="w", dependencies=["t0"],
                      max_retries=3, timeout_seconds=600,
                      status=TaskStatus.COMPLETED, output="done")
    spec = ft.to_task_node_spec()
    assert spec.task_id == "t1"
    assert spec.assigned_agent == "w"
    assert spec.max_retries == 3
    # Runtime fields should NOT be in spec
    assert not hasattr(spec, 'output')
    assert not hasattr(spec, 'retries')


def test_plan_file_task_to_task_result():
    from everstaff.schema.workflow_spec import PlanFileTask, TaskStatus
    ft = PlanFileTask(task_id="t1", title="T", description="d",
                      assigned_agent="w", status=TaskStatus.COMPLETED,
                      output="result", retries=2)
    result = ft.to_task_result()
    assert result.task_id == "t1"
    assert result.status == TaskStatus.COMPLETED
    assert result.output == "result"
    assert result.retries == 2
    assert result.agent_name == "w"


def test_plan_spec_status_values():
    """PlanSpec status does not include 'approved', includes 'stopped'."""
    from everstaff.schema.workflow_spec import PlanSpec

    for status in ["draft", "executing", "completed", "failed", "stopped"]:
        p = PlanSpec(title="t", goal="g", status=status)
        assert p.status == status

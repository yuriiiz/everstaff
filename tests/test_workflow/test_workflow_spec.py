"""Tests for workflow specification models (Schema layer)."""

import pytest
from datetime import datetime

from everstaff.schema.workflow_spec import (
    PlanSpec,
    TaskEvaluation,
    TaskNodeSpec,
    TaskResult,
    TaskStatus,
    WorkflowRecord,
    WorkflowResult,
    WorkflowSpec,
    plan_to_markdown,
)


# ---------------------------------------------------------------------------
# TaskNodeSpec
# ---------------------------------------------------------------------------

def test_task_node_spec_defaults():
    task = TaskNodeSpec(task_id="t1", title="Test", description="A task")
    assert task.max_retries == 2
    assert task.requires_evaluation is False
    assert task.timeout_seconds == 300
    assert task.dependencies == []
    assert task.assigned_agent is None


# ---------------------------------------------------------------------------
# PlanSpec.validate_dag
# ---------------------------------------------------------------------------

def test_plan_spec_validate_dag_valid():
    plan = PlanSpec(tasks=[
        TaskNodeSpec(task_id="a", title="A", description=""),
        TaskNodeSpec(task_id="b", title="B", description="", dependencies=["a"]),
        TaskNodeSpec(task_id="c", title="C", description="", dependencies=["b"]),
    ])
    errors = plan.validate_dag()
    assert errors == []


def test_plan_spec_validate_dag_cycle():
    plan = PlanSpec(tasks=[
        TaskNodeSpec(task_id="a", title="A", description="", dependencies=["b"]),
        TaskNodeSpec(task_id="b", title="B", description="", dependencies=["a"]),
    ])
    errors = plan.validate_dag()
    assert any("cycle" in e.lower() for e in errors)


def test_plan_spec_validate_dag_missing_dep():
    plan = PlanSpec(tasks=[
        TaskNodeSpec(task_id="a", title="A", description="", dependencies=["nonexistent"]),
    ])
    errors = plan.validate_dag()
    assert any("unknown" in e.lower() for e in errors)


def test_plan_spec_validate_dag_duplicate_id():
    plan = PlanSpec(tasks=[
        TaskNodeSpec(task_id="dup", title="First", description=""),
        TaskNodeSpec(task_id="dup", title="Second", description=""),
    ])
    errors = plan.validate_dag()
    assert any("duplicate" in e.lower() for e in errors)


# ---------------------------------------------------------------------------
# PlanSpec.topological_order
# ---------------------------------------------------------------------------

def test_topological_order_linear():
    plan = PlanSpec(tasks=[
        TaskNodeSpec(task_id="a", title="A", description=""),
        TaskNodeSpec(task_id="b", title="B", description="", dependencies=["a"]),
        TaskNodeSpec(task_id="c", title="C", description="", dependencies=["b"]),
    ])
    order = plan.topological_order()
    assert order == ["a", "b", "c"]


def test_topological_order_parallel():
    plan = PlanSpec(tasks=[
        TaskNodeSpec(task_id="b", title="B", description=""),
        TaskNodeSpec(task_id="a", title="A", description=""),
    ])
    order = plan.topological_order()
    # Alphabetical since they have equal in-degree
    assert order == ["a", "b"]


def test_topological_order_diamond():
    plan = PlanSpec(tasks=[
        TaskNodeSpec(task_id="a", title="A", description=""),
        TaskNodeSpec(task_id="b", title="B", description="", dependencies=["a"]),
        TaskNodeSpec(task_id="c", title="C", description="", dependencies=["a"]),
        TaskNodeSpec(task_id="d", title="D", description="", dependencies=["b", "c"]),
    ])
    order = plan.topological_order()
    assert order[0] == "a"
    assert order[-1] == "d"
    # b and c should both be in the middle
    assert set(order[1:3]) == {"b", "c"}


# ---------------------------------------------------------------------------
# plan_to_markdown
# ---------------------------------------------------------------------------

def test_plan_to_markdown_output():
    plan = PlanSpec(
        title="Test Plan",
        goal="Do things",
        tasks=[
            TaskNodeSpec(
                task_id="t1",
                title="Research",
                description="Find stuff",
                assigned_agent="researcher",
            ),
            TaskNodeSpec(
                task_id="t2",
                title="Build",
                description="Make stuff",
                assigned_agent="coder",
                dependencies=["t1"],
            ),
        ],
    )
    md = plan_to_markdown(plan)
    assert "Test Plan" in md
    assert "Research" in md
    assert "researcher" in md
    assert "t1" in md
    assert "→" in md  # dependency graph arrow


# ---------------------------------------------------------------------------
# WorkflowSpec
# ---------------------------------------------------------------------------

def test_workflow_spec_defaults():
    spec = WorkflowSpec()
    assert spec.max_replans == 3
    assert spec.max_parallel == 5


# ---------------------------------------------------------------------------
# WorkflowResult
# ---------------------------------------------------------------------------

def test_workflow_result_serialization():
    result = WorkflowResult(
        plan=PlanSpec(title="Test", goal="Goal"),
        results={
            "t1": TaskResult(task_id="t1", status=TaskStatus.COMPLETED, output="done"),
        },
        status="completed",
        replan_count=1,
        started_at=datetime(2024, 1, 1),
        completed_at=datetime(2024, 1, 2),
        summary="All done.",
    )
    data = result.model_dump()
    restored = WorkflowResult.model_validate(data)
    assert restored.status == "completed"
    assert restored.replan_count == 1
    assert "t1" in restored.results
    assert restored.results["t1"].status == TaskStatus.COMPLETED


# ---------------------------------------------------------------------------
# PlanSpec.get_task
# ---------------------------------------------------------------------------

def test_plan_get_task_found_and_missing():
    plan = PlanSpec(tasks=[
        TaskNodeSpec(task_id="x", title="X", description=""),
    ])
    assert plan.get_task("x") is not None
    assert plan.get_task("x").title == "X"
    assert plan.get_task("missing") is None


# ---------------------------------------------------------------------------
# End of tests
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# WorkflowRecord
# ---------------------------------------------------------------------------

def test_workflow_record_from_plan():
    plan = PlanSpec(
        plan_id="plan-1",
        title="My Plan",
        goal="Do stuff",
        tasks=[TaskNodeSpec(task_id="t1", title="Step 1", description="desc",
                            dependencies=[])],
    )
    record = WorkflowRecord.from_plan(plan)
    assert record.plan_id == "plan-1"
    assert record.title == "My Plan"
    assert record.status == "executing"
    assert len(record.tasks) == 1
    assert record.results == {}


def test_workflow_record_upsert_result():
    plan = PlanSpec(plan_id="p1", title="T", goal="G",
                    tasks=[TaskNodeSpec(task_id="t1", title="T1", description="d",
                                        dependencies=[])])
    record = WorkflowRecord.from_plan(plan)
    result = TaskResult(task_id="t1", status=TaskStatus.COMPLETED, output="done")
    record.results["t1"] = result
    assert record.results["t1"].status == TaskStatus.COMPLETED


# ---------------------------------------------------------------------------
# AgentSpec.hitl_mode
# ---------------------------------------------------------------------------

def test_agent_spec_hitl_mode_default():
    from everstaff.schema.agent_spec import AgentSpec
    spec = AgentSpec(agent_name="test")
    assert spec.hitl_mode == "on_request"

def test_agent_spec_hitl_mode_never():
    from everstaff.schema.agent_spec import AgentSpec
    spec = AgentSpec(agent_name="test", hitl_mode="never")
    assert spec.hitl_mode == "never"

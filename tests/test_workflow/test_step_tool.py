# tests/test_workflow/test_step_tool.py
import pytest
from unittest.mock import MagicMock, AsyncMock
from pathlib import Path


def write_test_plan(tmp_path, tasks, status="draft", max_parallel=5, plan_id="test-plan"):
    from everstaff.schema.workflow_spec import PlanSpec, PlanFileTask, TaskStatus
    file_tasks = []
    for t in tasks:
        ft = PlanFileTask(
            task_id=t["task_id"], title=t["title"], description=t["description"],
            assigned_agent=t.get("assigned_agent"),
            dependencies=t.get("dependencies", []),
            status=TaskStatus(t.get("status", "pending")),
            output=t.get("output", ""),
        )
        file_tasks.append(ft)
    plan = PlanSpec(
        plan_id=plan_id, title="Test Plan", goal="test",
        status=status, max_parallel=max_parallel, file_tasks=file_tasks,
    )
    plan_path = tmp_path / "plan" / f"{plan_id}.yaml"
    plan.save_yaml(plan_path)
    return plan_path


@pytest.mark.asyncio
async def test_step_tool_executes_ready_tasks(tmp_path):
    from everstaff.workflow.step_tool import ExecutePlanStepTool
    from everstaff.protocols import CancellationEvent
    from everstaff.schema.workflow_spec import PlanSpec, TaskStatus
    write_test_plan(tmp_path, [
        {"task_id": "t1", "title": "A", "description": "a", "assigned_agent": "w", "dependencies": []},
        {"task_id": "t2", "title": "B", "description": "b", "assigned_agent": "w", "dependencies": ["t1"]},
    ])
    factory = MagicMock()
    factory.run = AsyncMock(return_value="done")
    tool = ExecutePlanStepTool(
        factory=factory, cancellation=CancellationEvent(),
        tracer=None, session_id="s1", workdir=tmp_path,
    )
    result = await tool.execute({"plan_id": "test-plan"})
    assert not result.is_error
    assert "t1" in result.content
    loaded = PlanSpec.load_yaml(tmp_path / "plan" / "test-plan.yaml")
    t1 = next(t for t in loaded.file_tasks if t.task_id == "t1")
    assert t1.status == TaskStatus.COMPLETED
    t2 = next(t for t in loaded.file_tasks if t.task_id == "t2")
    assert t2.status == TaskStatus.PENDING
    assert loaded.status == "executing"


@pytest.mark.asyncio
async def test_step_tool_completes_plan(tmp_path):
    from everstaff.workflow.step_tool import ExecutePlanStepTool
    from everstaff.protocols import CancellationEvent
    from everstaff.schema.workflow_spec import PlanSpec
    write_test_plan(tmp_path, [
        {"task_id": "t1", "title": "A", "description": "a",
         "assigned_agent": "w", "dependencies": [],
         "status": "completed", "output": "done"},
    ], status="executing")
    factory = MagicMock()
    tool = ExecutePlanStepTool(
        factory=factory, cancellation=CancellationEvent(),
        tracer=None, session_id="s1", workdir=tmp_path,
    )
    result = await tool.execute({"plan_id": "test-plan"})
    assert not result.is_error
    loaded = PlanSpec.load_yaml(tmp_path / "plan" / "test-plan.yaml")
    assert loaded.status == "completed"


@pytest.mark.asyncio
async def test_step_tool_rejects_missing_plan(tmp_path):
    from everstaff.workflow.step_tool import ExecutePlanStepTool
    from everstaff.protocols import CancellationEvent
    tool = ExecutePlanStepTool(
        factory=MagicMock(), cancellation=CancellationEvent(),
        tracer=None, session_id="s1", workdir=tmp_path,
    )
    result = await tool.execute({"plan_id": "nonexistent"})
    assert result.is_error
    assert "not found" in result.content.lower()


@pytest.mark.asyncio
async def test_step_tool_changes_draft_to_executing(tmp_path):
    from everstaff.workflow.step_tool import ExecutePlanStepTool
    from everstaff.protocols import CancellationEvent
    from everstaff.schema.workflow_spec import PlanSpec
    write_test_plan(tmp_path, [
        {"task_id": "t1", "title": "A", "description": "a", "assigned_agent": "w", "dependencies": []},
    ], status="draft")
    factory = MagicMock()
    factory.run = AsyncMock(return_value="done")
    tool = ExecutePlanStepTool(
        factory=factory, cancellation=CancellationEvent(),
        tracer=None, session_id="s1", workdir=tmp_path,
    )
    await tool.execute({"plan_id": "test-plan"})
    loaded = PlanSpec.load_yaml(tmp_path / "plan" / "test-plan.yaml")
    assert loaded.status in ("executing", "completed")


@pytest.mark.asyncio
async def test_step_tool_progress_output(tmp_path):
    from everstaff.workflow.step_tool import ExecutePlanStepTool
    from everstaff.protocols import CancellationEvent
    write_test_plan(tmp_path, [
        {"task_id": "t1", "title": "First", "description": "a", "assigned_agent": "w", "dependencies": []},
        {"task_id": "t2", "title": "Second", "description": "b", "assigned_agent": "w", "dependencies": []},
        {"task_id": "t3", "title": "Third", "description": "c", "assigned_agent": "w", "dependencies": ["t1", "t2"]},
    ])
    factory = MagicMock()
    factory.run = AsyncMock(return_value="result")
    tool = ExecutePlanStepTool(
        factory=factory, cancellation=CancellationEvent(),
        tracer=None, session_id="s1", workdir=tmp_path,
    )
    result = await tool.execute({"plan_id": "test-plan"})
    assert "2" in result.content or "completed" in result.content.lower()


@pytest.mark.asyncio
async def test_step_tool_definition():
    from everstaff.workflow.step_tool import ExecutePlanStepTool
    from everstaff.protocols import CancellationEvent
    tool = ExecutePlanStepTool(
        factory=MagicMock(), cancellation=CancellationEvent(),
        tracer=None, session_id="s1", workdir=Path("/tmp"),
    )
    defn = tool.definition
    assert defn.name == "execute_plan_step"
    assert "plan_id" in defn.parameters["properties"]

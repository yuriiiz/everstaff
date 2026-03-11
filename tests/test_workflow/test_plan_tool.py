import pytest
from unittest.mock import MagicMock
from pathlib import Path


def make_factory(agents=None):
    factory = MagicMock()
    factory._agents = agents if agents is not None else {}
    return factory


@pytest.mark.asyncio
async def test_write_plan_creates_yaml_file(tmp_path):
    from everstaff.workflow.plan_tool import WritePlanTool
    from everstaff.protocols import CancellationEvent
    tool = WritePlanTool(
        factory=make_factory({"worker": MagicMock()}),
        max_parallel=3, cancellation=CancellationEvent(),
        tracer=None, session_id="s1", workdir=tmp_path,
    )
    result = await tool.execute({
        "goal": "test goal", "title": "Test Plan",
        "tasks": [{"task_id": "t1", "title": "Task 1", "description": "do it",
                   "assigned_agent": "worker", "dependencies": []}],
    })
    assert not result.is_error
    plan_files = list((tmp_path / "plan").glob("*.yaml"))
    assert len(plan_files) == 1
    from everstaff.schema.workflow_spec import PlanSpec
    loaded = PlanSpec.load_yaml(plan_files[0])
    assert loaded.title == "Test Plan"
    assert loaded.status == "draft"
    assert len(loaded.file_tasks) == 1
    assert loaded.file_tasks[0].task_id == "t1"
    assert loaded.max_parallel == 3


@pytest.mark.asyncio
async def test_write_plan_rejects_unknown_agent(tmp_path):
    from everstaff.workflow.plan_tool import WritePlanTool
    from everstaff.protocols import CancellationEvent
    tool = WritePlanTool(
        factory=make_factory({"worker": MagicMock()}),
        max_parallel=2, cancellation=CancellationEvent(),
        tracer=None, session_id="s1", workdir=tmp_path,
    )
    result = await tool.execute({
        "goal": "g", "title": "t",
        "tasks": [{"task_id": "t1", "title": "T", "description": "d",
                   "assigned_agent": "nonexistent", "dependencies": []}],
    })
    assert result.is_error
    assert "nonexistent" in result.content


@pytest.mark.asyncio
async def test_write_plan_rejects_cyclic_dag(tmp_path):
    from everstaff.workflow.plan_tool import WritePlanTool
    from everstaff.protocols import CancellationEvent
    tool = WritePlanTool(
        factory=make_factory({"w": MagicMock()}),
        max_parallel=2, cancellation=CancellationEvent(),
        tracer=None, session_id="s1", workdir=tmp_path,
    )
    result = await tool.execute({
        "goal": "g", "title": "t",
        "tasks": [
            {"task_id": "t1", "title": "A", "description": "a",
             "assigned_agent": "w", "dependencies": ["t2"]},
            {"task_id": "t2", "title": "B", "description": "b",
             "assigned_agent": "w", "dependencies": ["t1"]},
        ],
    })
    assert result.is_error
    assert "cycle" in result.content.lower()


@pytest.mark.asyncio
async def test_write_plan_returns_plan_id_in_content(tmp_path):
    from everstaff.workflow.plan_tool import WritePlanTool
    from everstaff.protocols import CancellationEvent
    tool = WritePlanTool(
        factory=make_factory({"w": MagicMock()}),
        max_parallel=2, cancellation=CancellationEvent(),
        tracer=None, session_id="s1", workdir=tmp_path,
    )
    result = await tool.execute({
        "goal": "g", "title": "t",
        "tasks": [{"task_id": "t1", "title": "T", "description": "d",
                   "assigned_agent": "w", "dependencies": []}],
    })
    assert not result.is_error
    assert "plan/" in result.content
    assert "t1" in result.content


@pytest.mark.asyncio
async def test_write_plan_tool_definition():
    from everstaff.workflow.plan_tool import WritePlanTool
    from everstaff.protocols import CancellationEvent
    tool = WritePlanTool(
        factory=MagicMock(_agents={}),
        max_parallel=2, cancellation=CancellationEvent(),
        tracer=None, session_id="s1", workdir=Path("/tmp"),
    )
    defn = tool.definition
    assert defn.name == "write_plan"
    assert "goal" in defn.parameters["properties"]
    assert "title" in defn.parameters["properties"]
    assert "tasks" in defn.parameters["properties"]

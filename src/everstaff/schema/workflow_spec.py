"""Workflow specification models — DAG tasks, plans, and workflow configuration."""

from __future__ import annotations

import uuid
import yaml
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from everstaff.schema.agent_spec import SubAgentSpec


class TaskStatus(str, Enum):
    """Lifecycle status of a single DAG task."""

    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class TaskNodeSpec(BaseModel):
    """A single task node in the execution DAG."""

    task_id: str
    title: str
    description: str
    assigned_agent: str | None = None
    dependencies: list[str] = Field(default_factory=list)
    acceptance_criteria: str | None = None
    max_retries: int = 2
    timeout_seconds: int = 300
    requires_evaluation: bool = False


class TaskEvaluation(BaseModel):
    """Coordinator's evaluation of a completed task."""

    meets_criteria: bool
    feedback: str
    score: float = 0.0  # 0.0 – 1.0


class TaskResult(BaseModel):
    """Result of executing a single DAG task."""

    task_id: str
    status: TaskStatus = TaskStatus.PENDING
    output: str = ""
    agent_name: str | None = None
    session_id: str | None = None
    retries: int = 0
    started_at: datetime | None = None
    completed_at: datetime | None = None
    evaluation: TaskEvaluation | None = None
    child_stats: Any = None  # SessionStats from the sub-agent run, if available


class PlanFileTask(BaseModel):
    """Merged TaskNodeSpec + TaskResult for YAML file I/O.

    Combines spec fields (what to do) with runtime fields (what happened)
    so a single YAML file can capture both the plan and its execution state.
    """

    # --- Spec fields (from TaskNodeSpec) ---
    task_id: str
    title: str
    description: str
    assigned_agent: str | None = None
    dependencies: list[str] = Field(default_factory=list)
    acceptance_criteria: str | None = None
    max_retries: int = 2
    timeout_seconds: int = 300
    requires_evaluation: bool = False

    # --- Runtime fields (from TaskResult) ---
    status: TaskStatus = TaskStatus.PENDING
    output: str = ""
    retries: int = 0
    started_at: datetime | None = None
    completed_at: datetime | None = None
    evaluation: TaskEvaluation | None = None

    def to_task_node_spec(self) -> TaskNodeSpec:
        """Extract a TaskNodeSpec from this file task."""
        return TaskNodeSpec(
            task_id=self.task_id,
            title=self.title,
            description=self.description,
            assigned_agent=self.assigned_agent,
            dependencies=list(self.dependencies),
            acceptance_criteria=self.acceptance_criteria,
            max_retries=self.max_retries,
            timeout_seconds=self.timeout_seconds,
            requires_evaluation=self.requires_evaluation,
        )

    def to_task_result(self) -> TaskResult:
        """Extract a TaskResult from this file task."""
        return TaskResult(
            task_id=self.task_id,
            status=self.status,
            output=self.output,
            agent_name=self.assigned_agent,
            retries=self.retries,
            started_at=self.started_at,
            completed_at=self.completed_at,
            evaluation=self.evaluation,
        )


class PlanSpec(BaseModel):
    """A plan containing a DAG of tasks."""

    plan_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str = ""
    goal: str = ""
    tasks: list[TaskNodeSpec] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    status: str = "draft"  # draft | executing | completed | failed | stopped
    max_parallel: int = 5
    file_tasks: list[PlanFileTask] = Field(default_factory=list)

    # --- DAG helpers ----------------------------------------------------------

    def get_task(self, task_id: str) -> TaskNodeSpec | None:
        """Lookup a task by ID."""
        for t in self.tasks:
            if t.task_id == task_id:
                return t
        return None

    def task_ids(self) -> list[str]:
        return [t.task_id for t in self.tasks]

    def validate_dag(self) -> list[str]:
        """Return a list of validation errors (empty == valid).

        Checks:
        1. No duplicate task IDs.
        2. All dependency references exist.
        3. No cycles (Kahn's algorithm).
        """
        errors: list[str] = []
        ids = self.task_ids()

        # Duplicate check
        seen: set[str] = set()
        for tid in ids:
            if tid in seen:
                errors.append(f"Duplicate task_id: {tid}")
            seen.add(tid)

        # Dependency existence
        id_set = set(ids)
        for t in self.tasks:
            for dep in t.dependencies:
                if dep not in id_set:
                    errors.append(f"Task '{t.task_id}' depends on unknown task '{dep}'")

        # Cycle detection via Kahn's topological sort
        in_degree: dict[str, int] = {t.task_id: 0 for t in self.tasks}
        adjacency: dict[str, list[str]] = {t.task_id: [] for t in self.tasks}
        for t in self.tasks:
            for dep in t.dependencies:
                if dep in adjacency:
                    adjacency[dep].append(t.task_id)
                    in_degree[t.task_id] += 1

        queue = [tid for tid, deg in in_degree.items() if deg == 0]
        visited = 0
        while queue:
            node = queue.pop(0)
            visited += 1
            for neighbor in adjacency.get(node, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if visited != len(self.tasks):
            errors.append("DAG contains a cycle")

        return errors

    def topological_order(self) -> list[str]:
        """Return task IDs in a valid topological order."""
        in_degree: dict[str, int] = {t.task_id: 0 for t in self.tasks}
        adjacency: dict[str, list[str]] = {t.task_id: [] for t in self.tasks}
        for t in self.tasks:
            for dep in t.dependencies:
                if dep in adjacency:
                    adjacency[dep].append(t.task_id)
                    in_degree[t.task_id] += 1

        queue = sorted(tid for tid, deg in in_degree.items() if deg == 0)
        order: list[str] = []
        while queue:
            node = queue.pop(0)
            order.append(node)
            for neighbor in sorted(adjacency.get(node, [])):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)
        return order

    # --- YAML file I/O --------------------------------------------------------

    def save_yaml(self, path: Path) -> None:
        """Serialize plan to a YAML file.

        Updates ``updated_at`` before writing.  Creates parent directories
        if they don't exist.  The ``tasks`` field is excluded from the
        output (use ``file_tasks`` instead).
        """
        self.updated_at = datetime.now()
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = self.model_dump(exclude={"tasks"}, mode="json")
        with open(path, "w", encoding="utf-8") as fh:
            yaml.dump(data, fh, default_flow_style=False, allow_unicode=True, sort_keys=False)

    @classmethod
    def load_yaml(cls, path: Path) -> "PlanSpec":
        """Deserialize a PlanSpec from a YAML file."""
        path = Path(path)
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        return cls.model_validate(data)


class WorkflowSpec(BaseModel):
    """Top-level workflow configuration, embeddable in AgentSpec."""

    enable: bool = False
    max_replans: int = 3
    max_parallel: int = 5


class WorkflowResult(BaseModel):
    """Final result of a complete workflow execution."""

    plan: PlanSpec
    results: dict[str, TaskResult] = Field(default_factory=dict)
    status: str = "completed"  # completed | failed | partial | stopped
    replan_count: int = 0
    started_at: datetime | None = None
    completed_at: datetime | None = None
    summary: str = ""


class WorkflowRecord(BaseModel):
    """Persistent snapshot of a workflow execution stored in session.json."""

    plan_id: str
    title: str
    goal: str
    status: str = "executing"  # executing | completed | failed | partial | stopped
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    tasks: list[TaskNodeSpec] = Field(default_factory=list)
    results: dict[str, TaskResult] = Field(default_factory=dict)

    @classmethod
    def from_plan(cls, plan: "PlanSpec") -> "WorkflowRecord":
        return cls(
            plan_id=plan.plan_id,
            title=plan.title,
            goal=plan.goal,
            status="executing",
            tasks=list(plan.tasks),
        )


def plan_to_markdown(plan: PlanSpec) -> str:
    """Render a PlanSpec as a human-readable Markdown document."""
    lines: list[str] = [
        f"## Plan: {plan.title}",
        "",
        f"**Goal:** {plan.goal}",
        f"**Status:** {plan.status}",
        "",
        "### Tasks",
        "",
    ]
    for t in plan.tasks:
        deps = ", ".join(t.dependencies) if t.dependencies else "none"
        agent = t.assigned_agent or "Coordinator"
        flags: list[str] = []
        if t.requires_evaluation:
            flags.append("eval")
        flag_str = f" [{', '.join(flags)}]" if flags else ""
        lines.append(
            f"- **[{t.task_id}]** {t.title} → Agent: {agent} | Deps: {deps}{flag_str}"
        )
        if t.description:
            lines.append(f"  {t.description}")

    # Simple dependency graph
    lines.extend(["", "### Dependency Graph", ""])
    topo = plan.topological_order()
    for tid in topo:
        task = plan.get_task(tid)
        if task and task.dependencies:
            for dep in task.dependencies:
                lines.append(f"{dep} → {tid}")
        elif task:
            lines.append(f"{tid} (root)")

    return "\n".join(lines)

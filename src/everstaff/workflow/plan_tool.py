"""WritePlanTool — NativeTool that validates a workflow DAG and writes it to a YAML plan file."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from everstaff.schema.workflow_spec import PlanFileTask, PlanSpec, TaskNodeSpec
from everstaff.protocols import CancellationEvent, ToolResult

if TYPE_CHECKING:
    from everstaff.workflow.factory import WorkflowSubAgentFactory
    from everstaff.protocols import TracingBackend


class WritePlanTool:
    name = "write_plan"

    def __init__(
        self,
        factory: "WorkflowSubAgentFactory",
        max_parallel: int,
        cancellation: CancellationEvent,
        tracer: "TracingBackend | None",
        session_id: str,
        workdir: Path,
        coordinator_name: str = "",
    ) -> None:
        self._factory = factory
        self._max_parallel = max_parallel
        self._cancellation = cancellation
        self._tracer = tracer
        self._session_id = session_id
        self._workdir = Path(workdir)
        self._coordinator_name = coordinator_name
        self._definition = self._build_definition()

    def _build_definition(self):
        """Build the protocols.ToolDefinition for registry registration."""
        from everstaff.protocols import ToolDefinition
        return ToolDefinition(
            name="write_plan",
            description=(
                "Create a workflow plan as a DAG and save it to a file. "
                "Does NOT execute any tasks — use execute_plan_step to run tasks."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "goal": {
                        "type": "string",
                        "description": "The user's overall goal",
                    },
                    "title": {
                        "type": "string",
                        "description": "Short title for this workflow",
                    },
                    "tasks": {
                        "type": "array",
                        "description": (
                            "List of task objects. Each requires: task_id, title, description, "
                            "assigned_agent (must match available sub-agent name), "
                            "dependencies (list of task_ids). "
                            "Optional: acceptance_criteria, max_retries (default 2), "
                            "requires_evaluation (default false)."
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "task_id": {"type": "string"},
                                "title": {"type": "string"},
                                "description": {"type": "string"},
                                "assigned_agent": {"type": "string"},
                                "dependencies": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "acceptance_criteria": {"type": "string"},
                                "max_retries": {"type": "integer"},
                                "requires_evaluation": {"type": "boolean"},
                            },
                            "required": ["task_id", "title", "description",
                                         "assigned_agent", "dependencies"],
                        },
                    },
                },
                "required": ["goal", "title", "tasks"],
            },
        )

    @property
    def definition(self):
        return self._definition

    def get_definition(self) -> Any:
        """Return the ToolDefinition for registry registration."""
        return self._definition

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        # 1. Parse tasks into TaskNodeSpec list
        task_specs = [TaskNodeSpec(**t) for t in args["tasks"]]

        # 2. Create PlanSpec with status="draft"
        plan = PlanSpec(
            goal=args["goal"],
            title=args["title"],
            tasks=task_specs,
            max_parallel=self._max_parallel,
            status="draft",
        )

        # 3. Validate agents exist
        available = set(self._factory._agents.keys())
        unknown_agents = [
            t.assigned_agent
            for t in plan.tasks
            if t.assigned_agent and t.assigned_agent not in available
        ]
        if unknown_agents:
            msg = (
                f"Plan rejected: unknown assigned_agent(s): {unknown_agents}. "
                f"Available agents: {sorted(available)}"
            )
            return ToolResult(tool_call_id="", content=msg, is_error=True)

        # 4. Validate DAG
        dag_errors = plan.validate_dag()
        if dag_errors:
            msg = "Plan rejected — DAG validation errors:\n" + "\n".join(dag_errors)
            return ToolResult(tool_call_id="", content=msg, is_error=True)

        # 5. Convert TaskNodeSpec list to PlanFileTask list
        file_tasks = [
            PlanFileTask(
                task_id=t.task_id,
                title=t.title,
                description=t.description,
                assigned_agent=t.assigned_agent,
                dependencies=list(t.dependencies),
                acceptance_criteria=t.acceptance_criteria,
                max_retries=t.max_retries,
                timeout_seconds=t.timeout_seconds,
                requires_evaluation=t.requires_evaluation,
            )
            for t in task_specs
        ]
        plan.file_tasks = file_tasks

        # 6. Write to {workdir}/plan/{plan_id}.yaml
        plan_dir = self._workdir / "plan"
        plan_path = plan_dir / f"{plan.plan_id}.yaml"
        plan.save_yaml(plan_path)

        # 7. Build result summary
        task_lines = []
        for ft in file_tasks:
            deps = ", ".join(ft.dependencies) if ft.dependencies else "none"
            task_lines.append(f"  - [{ft.task_id}] {ft.title} (agent: {ft.assigned_agent}, deps: {deps})")

        summary = (
            f"Plan written to plan/{plan.plan_id}.yaml\n"
            f"plan_id: {plan.plan_id}\n"
            f"title: {plan.title}\n"
            f"tasks ({len(file_tasks)}):\n" + "\n".join(task_lines)
        )

        return ToolResult(tool_call_id="", content=summary, is_error=False)

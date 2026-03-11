"""ExecutePlanStepTool — NativeTool that executes one round of ready tasks in a workflow plan."""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from everstaff.schema.workflow_spec import PlanSpec, TaskStatus
from everstaff.protocols import CancellationEvent, ToolResult, TraceEvent

if TYPE_CHECKING:
    from everstaff.workflow.factory import WorkflowSubAgentFactory
    from everstaff.protocols import TracingBackend

logger = logging.getLogger(__name__)


class ExecutePlanStepTool:
    """NativeTool that reads a plan YAML, executes one round of ready tasks,
    updates the file, and returns progress."""

    name = "execute_plan_step"

    def __init__(
        self,
        factory: "WorkflowSubAgentFactory",
        cancellation: CancellationEvent,
        tracer: "TracingBackend | None",
        session_id: str,
        workdir: Path,
        coordinator_name: str = "",
        memory: Any = None,
    ) -> None:
        self._factory = factory
        self._cancellation = cancellation
        self._tracer = tracer
        self._session_id = session_id
        self._workdir = Path(workdir)
        self._coordinator_name = coordinator_name
        self._memory = memory
        self._definition = self._build_definition()

    def _build_definition(self):
        """Build the protocols.ToolDefinition for registry registration."""
        from everstaff.protocols import ToolDefinition
        return ToolDefinition(
            name="execute_plan_step",
            description=(
                "Execute the next round of ready tasks in a workflow plan. "
                "Reads the plan file, runs all tasks whose dependencies are met "
                "in parallel, updates the file, and returns progress. "
                "Call repeatedly until the plan is completed."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "plan_id": {
                        "type": "string",
                        "description": "The plan ID — matches filename plan/{plan_id}.yaml",
                    },
                },
                "required": ["plan_id"],
            },
        )

    @property
    def definition(self):
        return self._definition

    def get_definition(self) -> Any:
        """Return the ToolDefinition for registry registration."""
        return self._definition

    def _emit(self, kind: str, data: dict, duration_ms: float | None = None) -> None:
        if self._tracer is None:
            return
        self._tracer.on_event(TraceEvent(
            kind=kind,
            session_id=self._session_id,
            data=data,
            duration_ms=duration_ms,
        ))

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        from everstaff.workflow.dag_engine import DAGEngine

        plan_id = args["plan_id"]
        plan_path = self._workdir / "plan" / f"{plan_id}.yaml"

        # 1. Read plan file — error if not found
        if not plan_path.exists():
            return ToolResult(
                tool_call_id="",
                content=f"Plan not found: plan/{plan_id}.yaml",
                is_error=True,
            )

        plan = PlanSpec.load_yaml(plan_path)

        # 2. Check plan status — error if already completed/failed/stopped
        if plan.status in ("completed", "failed", "stopped"):
            return ToolResult(
                tool_call_id="",
                content=f"Plan '{plan_id}' is already {plan.status}. Cannot execute further steps.",
                is_error=True,
            )

        # 3. If draft, change to executing
        if plan.status == "draft":
            plan.status = "executing"

        # 4. Build TaskNodeSpec list from file_tasks
        task_node_specs = [ft.to_task_node_spec() for ft in plan.file_tasks]
        plan.tasks = task_node_specs

        # 5. Build completed_results from file_tasks that are COMPLETED or SKIPPED
        completed_results = {}
        for ft in plan.file_tasks:
            if ft.status in (TaskStatus.COMPLETED, TaskStatus.SKIPPED):
                completed_results[ft.task_id] = ft.to_task_result()

        # 6. Create DAGEngine, seed with completed_results
        engine = DAGEngine(
            plan=plan,
            factory=self._factory,
            cancellation=self._cancellation,
            tracer=self._tracer,
            session_id=self._session_id,
            max_parallel=plan.max_parallel,
            coordinator_name=self._coordinator_name,
            memory=self._memory,
        )
        engine.seed_completed_results(completed_results)

        # 7. Execute one step
        self._emit("workflow_step_start", {
            "plan_id": plan_id,
            "title": plan.title,
        })
        t0 = time.monotonic()

        try:
            step_result = await engine.execute_step()
        except Exception as e:
            duration_ms = (time.monotonic() - t0) * 1000
            self._emit("workflow_step_end", {
                "plan_id": plan_id,
                "status": "error",
                "error": str(e),
            }, duration_ms=duration_ms)
            return ToolResult(
                tool_call_id="",
                content=f"Error executing plan step: {e}",
                is_error=True,
            )

        duration_ms = (time.monotonic() - t0) * 1000

        # 8. Update plan.file_tasks with results from engine.results
        all_results = engine.results
        for ft in plan.file_tasks:
            if ft.task_id in all_results:
                result = all_results[ft.task_id]
                ft.status = result.status
                ft.output = result.output or ""
                ft.retries = result.retries
                ft.started_at = result.started_at
                ft.completed_at = result.completed_at
                ft.evaluation = result.evaluation

        # 9. If plan is done, set final status
        if step_result.is_plan_done:
            if step_result.failed_tasks:
                plan.status = "failed"
            else:
                # Check if any file_task is FAILED
                has_failures = any(
                    ft.status == TaskStatus.FAILED for ft in plan.file_tasks
                )
                plan.status = "failed" if has_failures else "completed"

        # 10. Write updated plan file
        plan.save_yaml(plan_path)

        # 11. Emit trace
        self._emit("workflow_step_end", {
            "plan_id": plan_id,
            "title": plan.title,
            "status": plan.status,
            "completed_this_round": sorted(step_result.completed_tasks),
            "failed_this_round": sorted(step_result.failed_tasks),
            "is_plan_done": step_result.is_plan_done,
        }, duration_ms=duration_ms)

        # 12. Build progress summary
        summary = self._build_progress_summary(plan, step_result, all_results)

        return ToolResult(
            tool_call_id="",
            content=summary,
            is_error=False,
            child_stats=step_result.child_stats,
        )

    def _build_progress_summary(
        self,
        plan: PlanSpec,
        step_result: Any,
        all_results: dict,
    ) -> str:
        """Build a Markdown progress summary."""
        total = len(plan.file_tasks)
        completed_count = sum(
            1 for ft in plan.file_tasks
            if ft.status in (TaskStatus.COMPLETED, TaskStatus.SKIPPED)
        )

        lines = [f"## Plan Progress: {plan.title} ({completed_count}/{total} completed)", ""]

        # Completed this round
        if step_result.completed_tasks:
            lines.append("**Completed this round:**")
            for tid in sorted(step_result.completed_tasks):
                ft = next((f for f in plan.file_tasks if f.task_id == tid), None)
                title = ft.title if ft else tid
                output_preview = (ft.output[:200] if ft and ft.output else "")
                lines.append(f"- [{tid}] {title}: {output_preview}")
            lines.append("")

        # Failed this round
        if step_result.failed_tasks:
            lines.append("**Failed this round:**")
            for tid in sorted(step_result.failed_tasks):
                ft = next((f for f in plan.file_tasks if f.task_id == tid), None)
                title = ft.title if ft else tid
                error_msg = (ft.output[:200] if ft and ft.output else "unknown error")
                lines.append(f"- [{tid}] {title}: {error_msg}")
            lines.append("")

        # Next ready tasks
        pending_tasks = [
            ft for ft in plan.file_tasks if ft.status == TaskStatus.PENDING
        ]
        if pending_tasks and not step_result.is_plan_done:
            # Find which pending tasks have all deps met
            done_ids = {
                ft.task_id for ft in plan.file_tasks
                if ft.status in (TaskStatus.COMPLETED, TaskStatus.SKIPPED)
            }
            ready = [
                ft for ft in pending_tasks
                if all(dep in done_ids for dep in ft.dependencies)
            ]
            if ready:
                lines.append("**Next ready:**")
                for ft in ready:
                    lines.append(f"- [{ft.task_id}] {ft.title} (ready)")
                lines.append("")

        # Plan completion message
        if step_result.is_plan_done:
            succeeded = sum(
                1 for ft in plan.file_tasks if ft.status == TaskStatus.COMPLETED
            )
            failed = sum(
                1 for ft in plan.file_tasks if ft.status == TaskStatus.FAILED
            )
            if failed:
                lines.append(f"**Plan failed.** {succeeded}/{total} tasks succeeded, {failed} failed.")
            else:
                lines.append(f"**Plan completed.** {succeeded}/{total} tasks succeeded.")

        return "\n".join(lines)

"""DAGTool — NativeTool that accepts a workflow plan and drives DAGEngine."""
from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from everstaff.schema.workflow_spec import PlanSpec, TaskNodeSpec
from everstaff.protocols import CancellationEvent, ToolResult, TraceEvent

if TYPE_CHECKING:
    from everstaff.workflow.factory import WorkflowSubAgentFactory
    from everstaff.protocols import TracingBackend


class DAGTool:
    name = "write_workflow_plan"

    def __init__(
        self,
        factory: "WorkflowSubAgentFactory",
        max_parallel: int,
        cancellation: CancellationEvent,
        tracer: "TracingBackend | None",
        session_id: str,
        coordinator_name: str = "",
        memory: Any = None,
    ) -> None:
        self._factory = factory
        self._max_parallel = max_parallel
        self._cancellation = cancellation
        self._tracer = tracer
        self._session_id = session_id
        self._coordinator_name = coordinator_name
        self._memory = memory
        self._definition = self._build_definition()

    def _build_definition(self):
        """Build the protocols.ToolDefinition for registry registration."""
        from everstaff.protocols import ToolDefinition
        return ToolDefinition(
            name="write_workflow_plan",
            description=(
                "Submit a complete workflow plan as a DAG for execution. "
                "Tasks with no dependencies run in parallel. "
                "Call once with the full plan — blocks until all tasks complete."
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

        plan = PlanSpec(
            goal=args["goal"],
            title=args["title"],
            tasks=[TaskNodeSpec(**t) for t in args["tasks"]],
            status="approved",
        )

        # Early validation: all assigned_agents must be known
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

        self._emit("workflow_start", {
            "goal": plan.goal,
            "title": plan.title,
            "task_count": len(plan.tasks),
        })
        t0 = time.monotonic()

        engine = DAGEngine(
            plan=plan,
            factory=self._factory,
            cancellation=self._cancellation,
            tracer=self._tracer,
            session_id=self._session_id,
            max_parallel=self._max_parallel,
            coordinator_name=self._coordinator_name,
            memory=self._memory,
        )
        results = await engine.execute()

        duration_ms = (time.monotonic() - t0) * 1000
        failed_tasks = engine.get_failed_tasks()
        status = (
            "stopped" if self._cancellation.is_cancelled
            else ("failed" if failed_tasks else "completed")
        )

        self._emit("workflow_end", {
            "status": status,
            "task_count": len(plan.tasks),
        }, duration_ms=duration_ms)

        summary = self._build_summary(plan, results, status)

        # Aggregate child stats from all task results so the parent session
        # can record token usage across all sub-agents in children_calls.
        merged_child_stats = self._merge_task_stats(results)

        return ToolResult(
            tool_call_id="",
            content=summary,
            is_error=(status == "failed"),
            child_stats=merged_child_stats,
        )

    def _merge_task_stats(self, results: dict) -> "Any | None":
        """Collect SessionStats from all task results into a single SessionStats.

        The returned stats has all sub-agents' own_calls in its own_calls list.
        The parent runtime will call stats.merge(this) to move them to children_calls.
        """
        from everstaff.schema.token_stats import SessionStats, TokenUsage
        merged: SessionStats | None = None
        for task_result in results.values():
            task_stats = getattr(task_result, "child_stats", None)
            if task_stats is None:
                continue
            if merged is None:
                merged = SessionStats()
            # Copy sub-agent's own calls directly into merged.own_calls
            # (and also tool_calls_count, errors_count)
            for call in task_stats.own_calls:
                merged.own_calls.append(call)
            for call in task_stats.children_calls:
                merged.own_calls.append(call)
            merged.tool_calls_count += task_stats.tool_calls_count
            merged.errors_count += task_stats.errors_count
        return merged

    def get_definition(self) -> Any:
        """Return the ToolDefinition for registry registration."""
        return self._definition

    def _build_summary(self, plan: PlanSpec, results: dict, status: str) -> str:
        lines = [f"## Workflow {status.capitalize()}: {plan.title}", ""]
        for task in plan.tasks:
            res = results.get(task.task_id)
            s = res.status.value if res else "unknown"
            out = (res.output or "")[:500] if res else ""
            lines.append(f"### [{s.upper()}] {task.title}")
            if out:
                lines.append(out)
            lines.append("")
        return "\n".join(lines)

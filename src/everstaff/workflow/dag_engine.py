"""DAGEngine — executes a plan's task DAG with dependency resolution and parallel dispatch."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from everstaff.protocols import HumanApprovalRequired
from everstaff.schema.workflow_spec import (
    PlanSpec,
    TaskEvaluation,
    TaskNodeSpec,
    TaskResult,
    TaskStatus,
)

if TYPE_CHECKING:
    from everstaff.protocols import CancellationEvent, LLMClient, MemoryStore, TracingBackend
    from everstaff.workflow.factory import WorkflowSubAgentFactory

logger = logging.getLogger(__name__)

# -- Concise mode preamble injected into every sub-agent prompt ----------------
_CONCISE_PREAMBLE = """\
You are executing a specific task in a workflow. Be concise and focused:
- Output ONLY what the task requires — no greetings, recaps, or summaries.
- Do not explain your approach unless the task asks for it.
- If using tools, proceed directly without narration.
- End with the concrete deliverable, not a recap.
"""


class DAGEngine:
    """Drives a PlanSpec DAG to completion.

    Responsibilities:
    - Resolve ready tasks (all dependencies COMPLETED)
    - Dispatch tasks in parallel via WorkflowSubAgentFactory
    - Evaluate results (optional, per-task) using independent LLM calls
    - Handle retries and trigger replanning on persistent failure
    - Track progress as a Markdown summary
    """

    def __init__(
        self,
        plan: PlanSpec,
        factory: "WorkflowSubAgentFactory",
        cancellation: "CancellationEvent",
        tracer: "TracingBackend | None" = None,
        session_id: str = "",
        max_parallel: int = 5,
        coordinator_name: str = "",
        on_task_start: "Callable[[TaskNodeSpec], Awaitable[None]] | None" = None,
        on_task_complete: "Callable[[str, TaskResult], Awaitable[None]] | None" = None,
        on_plan_updated: "Callable[[PlanSpec], Awaitable[None]] | None" = None,
        llm_client: "LLMClient | None" = None,
        memory: "MemoryStore | None" = None,
    ) -> None:
        self._plan = plan
        self._factory = factory
        self._cancellation = cancellation
        self._tracer = tracer
        self._session_id = session_id
        self._max_parallel = max_parallel
        self._coordinator_name = coordinator_name
        self._on_task_start = on_task_start
        self._on_task_complete = on_task_complete
        self._on_plan_updated = on_plan_updated
        self._llm_client = llm_client
        self._memory = memory

        # Execution state
        self._results: dict[str, TaskResult] = {}
        self._task_status: dict[str, TaskStatus] = {
            t.task_id: TaskStatus.PENDING for t in plan.tasks
        }

        # Progress markdown (updated after each batch)
        self._progress_markdown: str = ""

    # ------------------------------------------------------------------
    # Persistence helper
    # ------------------------------------------------------------------

    async def _persist_workflow(self) -> None:
        """Write current plan + results snapshot to session.json."""
        if self._memory is None or not self._session_id:
            return
        from everstaff.schema.workflow_spec import WorkflowRecord
        record = WorkflowRecord(
            plan_id=self._plan.plan_id,
            title=self._plan.title,
            goal=self._plan.goal,
            status=self._plan.status,
            tasks=list(self._plan.tasks),
            results=dict(self._results),
            updated_at=datetime.now(),
        )
        try:
            await self._memory.save_workflow(self._session_id, record)
        except Exception as e:
            logger.warning("DAGEngine: failed to persist workflow: %s", e)

    # ------------------------------------------------------------------
    # Tracing helper
    # ------------------------------------------------------------------

    def _emit(self, kind: str, data: dict, duration_ms: float | None = None) -> None:
        if self._tracer is None:
            return
        from everstaff.protocols import TraceEvent
        self._tracer.on_event(TraceEvent(
            kind=kind,
            session_id=self._session_id,
            data=data,
            duration_ms=duration_ms,
        ))

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def results(self) -> dict[str, TaskResult]:
        return dict(self._results)

    @property
    def plan(self) -> PlanSpec:
        return self._plan

    @property
    def progress_markdown(self) -> str:
        """Return the current progress as a Markdown string."""
        return self._progress_markdown

    # ------------------------------------------------------------------
    # Recovery support
    # ------------------------------------------------------------------

    def seed_completed_results(self, completed_results: dict[str, TaskResult]) -> None:
        """Pre-seed the engine with results from previously completed tasks."""
        for task_id, result in completed_results.items():
            if task_id in self._task_status:
                if result.status in (TaskStatus.COMPLETED, TaskStatus.SKIPPED):
                    self._task_status[task_id] = result.status
                    self._results[task_id] = result

    # ------------------------------------------------------------------
    # Main execution loop
    # ------------------------------------------------------------------

    async def execute(self) -> dict[str, TaskResult]:
        """Run all tasks in the DAG to completion. Returns results keyed by task_id."""
        self._plan.status = "executing"

        while True:
            if self._cancellation.is_cancelled:
                logger.info("DAGEngine: Stop requested, ceasing dispatch.")
                for task in self._plan.tasks:
                    if self._task_status[task.task_id] == TaskStatus.PENDING:
                        self._task_status[task.task_id] = TaskStatus.SKIPPED
                        self._results[task.task_id] = TaskResult(
                            task_id=task.task_id,
                            status=TaskStatus.SKIPPED,
                            output="Workflow stopped by user.",
                        )
                self._plan.status = "stopped"
                if self._on_plan_updated:
                    try:
                        await self._on_plan_updated(self._plan)
                    except Exception as e:
                        logger.warning("on_plan_updated failed: %s", e)
                break

            ready = self._get_ready_tasks()

            running = [
                tid for tid, st in self._task_status.items() if st == TaskStatus.RUNNING
            ]
            if not ready and not running:
                break

            if not ready:
                await asyncio.sleep(0.5)
                continue

            # Limit concurrency
            batches = [
                ready[i : i + self._max_parallel]
                for i in range(0, len(ready), self._max_parallel)
            ]

            for batch in batches:
                for task in batch:
                    self._task_status[task.task_id] = TaskStatus.RUNNING
                    await self._persist_workflow()
                    if self._on_task_start:
                        try:
                            await self._on_task_start(task)
                        except Exception as e:
                            logger.warning("on_task_start callback failed: %s", e)

                coros = [self._execute_task(task) for task in batch]
                batch_results = await asyncio.gather(*coros, return_exceptions=True)

                # First pass: record all non-exception results
                hitl_exceptions: list[HumanApprovalRequired] = []
                for task, result in zip(batch, batch_results):
                    if isinstance(result, BaseException):
                        if isinstance(result, HumanApprovalRequired):
                            hitl_exceptions.append(result)
                        else:
                            failed_result = TaskResult(
                                task_id=task.task_id,
                                status=TaskStatus.FAILED,
                                output=f"Exception: {result}",
                            )
                            self._results[task.task_id] = failed_result
                            self._task_status[task.task_id] = failed_result.status
                            await self._persist_workflow()
                        continue

                    needs_eval = task.requires_evaluation or bool(task.acceptance_criteria)
                    if needs_eval and result.status == TaskStatus.COMPLETED:
                        evaluation = await self._evaluate_task(task, result)
                        result.evaluation = evaluation
                        if not evaluation.meets_criteria:
                            if result.retries < task.max_retries:
                                result.retries += 1
                                self._task_status[task.task_id] = TaskStatus.PENDING
                                self._results[task.task_id] = result
                                logger.info(
                                    "Task %s failed evaluation, retrying (%d/%d)",
                                    task.task_id,
                                    result.retries,
                                    task.max_retries,
                                )
                                continue
                            else:
                                result.status = TaskStatus.FAILED

                    self._results[task.task_id] = result
                    self._task_status[task.task_id] = result.status
                    await self._persist_workflow()

                    if self._on_task_complete:
                        try:
                            await self._on_task_complete(task.task_id, result)
                        except Exception:
                            logger.warning("on_task_complete callback failed for task %s", task.task_id)

                # Second pass: merge and raise all HITL exceptions after completed results are saved
                if hitl_exceptions:
                    all_requests = []
                    for exc in hitl_exceptions:
                        all_requests.extend(exc.requests)
                    raise HumanApprovalRequired(all_requests)  # propagate up to DAGTool → AgentRuntime

                self._update_progress_markdown()
                if self._on_plan_updated:
                    try:
                        await self._on_plan_updated(self._plan)
                    except Exception as e:
                        logger.warning("on_plan_updated failed: %s", e)

        if self._plan.status != "stopped":
            statuses = set(self._task_status.values())
            if TaskStatus.FAILED in statuses:
                self._plan.status = "failed"
            elif all(
                s in (TaskStatus.COMPLETED, TaskStatus.SKIPPED) for s in statuses
            ):
                self._plan.status = "completed"

        self._update_progress_markdown()
        await self._persist_workflow()
        if self._on_plan_updated:
            try:
                await self._on_plan_updated(self._plan)
            except Exception as e:
                logger.warning("on_plan_updated failed: %s", e)
        return dict(self._results)

    # ------------------------------------------------------------------
    # Task resolution
    # ------------------------------------------------------------------

    def _get_ready_tasks(self) -> list[TaskNodeSpec]:
        """Return tasks whose dependencies are all COMPLETED (or SKIPPED)."""
        ready: list[TaskNodeSpec] = []
        done_statuses = {TaskStatus.COMPLETED, TaskStatus.SKIPPED}

        for task in self._plan.tasks:
            if self._task_status[task.task_id] != TaskStatus.PENDING:
                continue
            deps_met = all(
                self._task_status.get(dep) in done_statuses
                for dep in task.dependencies
            )
            if deps_met:
                ready.append(task)
        return ready

    # ------------------------------------------------------------------
    # Task execution
    # ------------------------------------------------------------------

    async def _execute_task(self, task: TaskNodeSpec) -> TaskResult:
        """Execute a single task by delegating to the appropriate sub-agent via the factory."""
        agent = task.assigned_agent or self._coordinator_name  # resolve before constructing result
        result = TaskResult(
            task_id=task.task_id,
            status=TaskStatus.RUNNING,
            agent_name=agent,   # use resolved agent, not raw assigned_agent
            started_at=datetime.now(),
        )

        prompt = self._build_task_prompt(task)

        self._emit("workflow_task_start", {
            "task_id": task.task_id,
            "title": task.title,
            "assigned_agent": agent,   # emit resolved agent too
        })
        t0 = time.monotonic()

        try:
            if agent:
                # Use run_with_stats() if available and is a coroutine function
                # (WorkflowSubAgentFactory). Fall back to run() otherwise.
                import inspect
                _run_with_stats = getattr(self._factory, "run_with_stats", None)
                if _run_with_stats is not None and inspect.iscoroutinefunction(_run_with_stats):
                    output, task_child_stats = await asyncio.wait_for(
                        _run_with_stats(agent, prompt),
                        timeout=task.timeout_seconds,
                    )
                    result.child_stats = task_child_stats
                else:
                    output = await asyncio.wait_for(
                        self._factory.run(agent, prompt),
                        timeout=task.timeout_seconds,
                    )
            else:
                output = f"No agent assigned for task '{task.task_id}' and no coordinator configured."

            result.output = str(output)
            result.status = TaskStatus.COMPLETED
        except asyncio.TimeoutError:
            result.output = f"Task timed out after {task.timeout_seconds} seconds."
            result.status = TaskStatus.FAILED
            logger.warning("Task %s timed out after %ds", task.task_id, task.timeout_seconds)
        except Exception as e:
            result.output = f"Error: {e}"
            result.status = TaskStatus.FAILED
            logger.exception("Task %s failed", task.task_id)

        result.completed_at = datetime.now()

        duration_ms = (time.monotonic() - t0) * 1000
        self._emit("workflow_task_end", {
            "task_id": task.task_id,
            "status": result.status.value,
            "retries": result.retries,
        }, duration_ms=duration_ms)

        return result

    def _build_task_prompt(self, task: TaskNodeSpec) -> str:
        """Build the prompt sent to the sub-agent, including dependency outputs."""
        parts: list[str] = [_CONCISE_PREAMBLE]

        parts.extend([
            f"## Task: {task.title}",
            "",
            task.description,
        ])

        if task.acceptance_criteria:
            parts.extend(["", "## Acceptance Criteria", task.acceptance_criteria])

        dep_outputs: list[str] = []
        for dep_id in task.dependencies:
            dep_result = self._results.get(dep_id)
            if dep_result and dep_result.output:
                dep_task = self._plan.get_task(dep_id)
                title = dep_task.title if dep_task else dep_id
                output = dep_result.output
                if len(output) > 2000:
                    output = output[:2000] + "\n... (truncated)"
                dep_outputs.append(f"### [{dep_id}] {title}\n{output}")

        if dep_outputs:
            parts.extend(["", "## Outputs from Preceding Tasks", ""] + dep_outputs)

        if task.assigned_agent:
            agent_history: list[str] = []
            for tid, res in self._results.items():
                if (
                    tid != task.task_id
                    and res.agent_name == task.assigned_agent
                    and res.status == TaskStatus.COMPLETED
                    and tid not in task.dependencies
                ):
                    prev_task = self._plan.get_task(tid)
                    title = prev_task.title if prev_task else tid
                    summary = res.output[:1000] if res.output else "(no output)"
                    agent_history.append(f"### [{tid}] {title}\n{summary}")
            if agent_history:
                parts.extend(
                    ["", "## Your Previous Work (earlier tasks you completed)", ""]
                    + agent_history
                )

        prev_result = self._results.get(task.task_id)
        if prev_result and prev_result.evaluation and not prev_result.evaluation.meets_criteria:
            parts.extend([
                "",
                "## Previous Attempt Feedback",
                "Your previous output did not meet the criteria.",
                f"Feedback: {prev_result.evaluation.feedback}",
                "Please address this feedback in your new attempt.",
            ])

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    async def _evaluate_task(self, task: TaskNodeSpec, result: TaskResult) -> TaskEvaluation:
        """Evaluate whether a task result meets criteria using an independent LLM call."""

        if not self._llm_client:
            return TaskEvaluation(meets_criteria=True, feedback="No LLM client for evaluation.", score=1.0)

        from everstaff.protocols import Message

        eval_prompt = (
            f"Evaluate whether the following task output meets the acceptance criteria.\n\n"
            f"## Task: {task.title}\n{task.description}\n\n"
            f"## Acceptance Criteria\n{task.acceptance_criteria or '(none specified)'}\n\n"
            f"## Agent Output\n{result.output[:3000]}\n\n"
            f"Respond with a JSON object: "
            f'{{"meets_criteria": true/false, "feedback": "...", "score": 0.0-1.0}}'
        )

        messages = [
            Message(role="system", content="You are a task evaluator. Respond ONLY with a JSON object.", created_at=datetime.now(timezone.utc).isoformat()),
            Message(role="user", content=eval_prompt, created_at=datetime.now(timezone.utc).isoformat()),
        ]

        for attempt in range(3):
            try:
                response = await self._llm_client.complete(messages=messages, tools=[])

                eval_response = response.content or ""

                start = eval_response.find("{")
                end = eval_response.rfind("}") + 1
                if start >= 0 and end > start:
                    data = json.loads(eval_response[start:end])
                    return TaskEvaluation(
                        meets_criteria=data.get("meets_criteria", True),
                        feedback=data.get("feedback", ""),
                        score=data.get("score", 0.0),
                    )
                else:
                    logger.warning(
                        "Evaluation: No JSON object found in response for task %s (Attempt %d). Raw: %s",
                        task.task_id, attempt + 1, eval_response[:500],
                    )
                    messages.append(Message(role="assistant", content=eval_response, created_at=datetime.now(timezone.utc).isoformat()))
                    messages.append(Message(
                        role="user",
                        content="Your response was not a valid JSON object. Please respond ONLY with a JSON object.",
                        created_at=datetime.now(timezone.utc).isoformat(),
                    ))

            except Exception as e:
                logger.warning(
                    "Evaluation failed for task %s (Attempt %d): %s.",
                    task.task_id, attempt + 1, e,
                )

        return TaskEvaluation(meets_criteria=True, feedback="Evaluation inconclusive.", score=0.5)

    # ------------------------------------------------------------------
    # Progress tracking
    # ------------------------------------------------------------------

    def _update_progress_markdown(self) -> None:
        lines = [f"## Workflow Progress: {self._plan.title}", ""]
        for task in self._plan.tasks:
            status = self._task_status.get(task.task_id, TaskStatus.PENDING)
            agent = task.assigned_agent or "Coordinator"
            if status == TaskStatus.COMPLETED:
                mark = "x"
            elif status == TaskStatus.RUNNING:
                mark = "~"
            elif status in (TaskStatus.FAILED, TaskStatus.SKIPPED):
                mark = "!"
            else:
                mark = " "
            lines.append(f"- [{mark}] {task.task_id}: {task.title} ({status.value}) → {agent}")
        self._progress_markdown = "\n".join(lines)

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def get_failed_tasks(self) -> list[str]:
        """Return task IDs that failed execution."""
        return [tid for tid, r in self._results.items() if r.status == TaskStatus.FAILED]

    def get_status_summary(self) -> dict[str, Any]:
        """Return a summary of execution progress."""
        counts: dict[str, int] = {}
        for status in self._task_status.values():
            counts[status.value] = counts.get(status.value, 0) + 1
        return {
            "plan_id": self._plan.plan_id,
            "plan_status": self._plan.status,
            "task_counts": counts,
            "total_tasks": len(self._plan.tasks),
        }

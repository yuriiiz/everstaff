"""
ThinkEngine — Tool-based decision making for the autonomous agent.

The brain of the autonomous agent loop. When triggered, the ThinkEngine
builds context from DaemonStateStore (structured state) and optionally
Mem0Client (long-term semantic memory), presents it to an LLM along with
tool definitions, and runs a tool loop until the LLM calls ``make_decision``
to produce a :class:`Decision`.

Tools available to the LLM during thinking:
- ``make_decision`` — commit to an action (execute / skip / defer)
- ``search_memory`` — search long-term memory via Mem0
- ``break_down_goal`` — decompose a goal into sub-goals
- ``update_goal_progress`` — update sub-goal status
- ``record_learning_insight`` — persist a learning insight to long-term memory
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from everstaff.daemon.goals import GoalBreakdown, SubGoal
from everstaff.protocols import Decision, Message, ToolDefinition, ToolResult
from everstaff.tools.default_registry import DefaultToolRegistry

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from everstaff.protocols import AgentEvent

# ---------------------------------------------------------------------------
# Think tool context — shared mutable state for think-phase tools
# ---------------------------------------------------------------------------


@dataclass
class ThinkToolContext:
    """Shared context passed to every think-tool handler."""

    agent_name: str
    agent_uuid: str
    state: Any  # DaemonState
    state_store: Any  # DaemonStateStore
    mem0: Any  # Optional Mem0Client
    decision: Decision | None = field(default=None, init=False)


# ---------------------------------------------------------------------------
# Think tools — each implements the Tool protocol
# ---------------------------------------------------------------------------


class MakeDecisionTool:
    def __init__(self, ctx: ThinkToolContext) -> None:
        self._ctx = ctx

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="make_decision",
            description="Make a decision about what to do. Call this when you've decided.",
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["execute", "skip", "defer"],
                        "description": "What to do",
                    },
                    "task_prompt": {
                        "type": "string",
                        "description": "The task description if action=execute",
                    },
                    "reasoning": {
                        "type": "string",
                        "description": "Why you made this decision",
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["high", "normal", "low"],
                        "description": "Task priority",
                    },
                },
                "required": ["action", "reasoning"],
            },
        )

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        decision = Decision(
            action=args.get("action", "skip"),
            reasoning=args.get("reasoning", ""),
            task_prompt=args.get("task_prompt", ""),
            priority=args.get("priority", "normal"),
        )
        logger.info(
            "decision made agent=%s action=%s priority=%s task=%s",
            self._ctx.agent_name, decision.action, decision.priority,
            decision.task_prompt[:80] if decision.task_prompt else "-",
        )
        self._ctx.decision = decision
        return ToolResult(tool_call_id="", content=f"Decision '{decision.action}' recorded.")


class SearchMemoryTool:
    def __init__(self, ctx: ThinkToolContext) -> None:
        self._ctx = ctx

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="search_memory",
            description="Search long-term memory for relevant historical context (past episodes, patterns, insights).",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to search for"},
                },
                "required": ["query"],
            },
        )

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        query = args.get("query", "")
        logger.debug("tool call search_memory agent=%s query=%s", self._ctx.agent_name, query[:80])
        if self._ctx.mem0 is None:
            content = "(memory not enabled)"
        else:
            results = await self._ctx.mem0.search(query, agent_id=self._ctx.agent_name)
            content = "\n".join(r.get("memory", str(r)) for r in results) if results else "(no results)"
        return ToolResult(tool_call_id="", content=content)


class BreakDownGoalTool:
    def __init__(self, ctx: ThinkToolContext) -> None:
        self._ctx = ctx

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="break_down_goal",
            description="Break a user-defined goal into actionable sub-goals. The user's original goal is preserved and immutable.",
            parameters={
                "type": "object",
                "properties": {
                    "goal_id": {"type": "string", "description": "The GoalConfig id to break down"},
                    "sub_goals": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "description": {"type": "string"},
                                "acceptance_criteria": {"type": "string"},
                            },
                            "required": ["description"],
                        },
                    },
                },
                "required": ["goal_id", "sub_goals"],
            },
        )

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        goal_id = args["goal_id"]
        raw_subs = args.get("sub_goals", [])
        logger.debug("tool call break_down_goal agent=%s goal_id=%s sub_goals=%d",
                      self._ctx.agent_name, goal_id, len(raw_subs))
        sub_goals = [
            SubGoal(description=s["description"], acceptance_criteria=s.get("acceptance_criteria", ""))
            for s in raw_subs
        ]
        gb = GoalBreakdown(goal_id=goal_id, sub_goals=sub_goals)
        self._ctx.state.goals_breakdown[goal_id] = gb
        await self._ctx.state_store.save(self._ctx.agent_uuid, self._ctx.state)
        return ToolResult(tool_call_id="", content=f"Goal '{goal_id}' broken into {len(sub_goals)} sub-goals.")


class UpdateGoalProgressTool:
    def __init__(self, ctx: ThinkToolContext) -> None:
        self._ctx = ctx

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="update_goal_progress",
            description="Update the status of a daemon-maintained sub-goal.",
            parameters={
                "type": "object",
                "properties": {
                    "goal_id": {"type": "string"},
                    "sub_goal_index": {"type": "integer", "description": "0-based index"},
                    "status": {"type": "string", "enum": ["pending", "in_progress", "completed", "blocked"]},
                    "progress_note": {"type": "string"},
                },
                "required": ["goal_id", "sub_goal_index", "status"],
            },
        )

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        goal_id = args["goal_id"]
        idx = args["sub_goal_index"]
        status = args["status"]
        note = args.get("progress_note", "")
        logger.debug("tool call update_goal_progress agent=%s goal_id=%s idx=%d status=%s",
                      self._ctx.agent_name, goal_id, idx, status)
        if goal_id not in self._ctx.state.goals_breakdown:
            content = f"Error: no breakdown for goal '{goal_id}'"
        else:
            gb = self._ctx.state.goals_breakdown[goal_id]
            if idx < 0 or idx >= len(gb.sub_goals):
                content = f"Error: sub_goal_index {idx} out of range (0-{len(gb.sub_goals) - 1})"
            else:
                gb.sub_goals[idx].status = status
                if note:
                    gb.sub_goals[idx].progress_note = note
                await self._ctx.state_store.save(self._ctx.agent_uuid, self._ctx.state)
                content = f"Sub-goal {idx} of '{goal_id}' updated to '{status}'. Completion: {gb.completion_ratio:.0%}"
        return ToolResult(tool_call_id="", content=content)


class RecordLearningInsightTool:
    def __init__(self, ctx: ThinkToolContext) -> None:
        self._ctx = ctx

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="record_learning_insight",
            description="Record a learning insight from analyzing recent episodes. Insights are persisted and inform future decisions.",
            parameters={
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": ["pattern", "optimization", "risk", "capability_gap"],
                    },
                    "insight": {"type": "string", "description": "What was learned"},
                    "evidence": {"type": "string", "description": "Episode IDs or summary supporting this"},
                    "action": {"type": "string", "description": "Recommended follow-up action"},
                },
                "required": ["category", "insight", "evidence"],
            },
        )

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        logger.debug("tool call record_learning_insight agent=%s category=%s",
                      self._ctx.agent_name, args.get("category"))
        if self._ctx.mem0 is None:
            content = "(memory not enabled, insight not persisted)"
        else:
            text = f"[{args['category']}] {args['insight']} (evidence: {args['evidence']})"
            if args.get("action"):
                text += f" -> action: {args['action']}"
            await self._ctx.mem0.add(
                [{"role": "assistant", "content": text}],
                agent_id=self._ctx.agent_name,
            )
            content = "Insight recorded."
        return ToolResult(tool_call_id="", content=content)


THINK_TOOL_CLASSES = [
    MakeDecisionTool,
    SearchMemoryTool,
    BreakDownGoalTool,
    UpdateGoalProgressTool,
    RecordLearningInsightTool,
]

_MAX_THINK_ITERATIONS = 5


def _build_think_registry(ctx: ThinkToolContext) -> DefaultToolRegistry:
    """Build a ToolRegistry populated with think-phase tools."""
    registry = DefaultToolRegistry()
    for cls in THINK_TOOL_CLASSES:
        registry.register(cls(ctx))
    return registry


class ThinkEngine:
    """LLM-powered decision engine for the autonomous agent loop.

    Parameters
    ----------
    llm_client:
        Any object satisfying the ``LLMClient`` protocol.
    tracer:
        Any object satisfying the ``TracingBackend`` protocol.
    daemon_state_store:
        A ``DaemonStateStore`` instance for structured state persistence.
    agent_uuid:
        The unique identifier for this agent.
    mem0_client:
        Optional ``Mem0Client`` for long-term semantic memory.
    """

    def __init__(self, llm_client: Any, tracer: Any, daemon_state_store: Any, agent_uuid: str, mem0_client: Any = None) -> None:
        self._llm = llm_client
        self._tracer = tracer
        self._state_store = daemon_state_store
        self._agent_uuid = agent_uuid
        self._mem0 = mem0_client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def think(
        self,
        agent_name: str,
        trigger: AgentEvent,
        pending_events: list[AgentEvent],
        autonomy_goals: list[Any],
    ) -> tuple[Decision, list[Message]]:
        """Run the think loop and return a :class:`Decision` with messages.

        The loop sends messages (with context) to the LLM and processes
        tool calls.  It terminates when the LLM calls ``make_decision``
        or after ``_MAX_THINK_ITERATIONS`` rounds.
        """
        logger.info("starting agent=%s trigger=%s:%s pending=%d goals=%d",
                     agent_name, trigger.source, trigger.type, len(pending_events), len(autonomy_goals))

        # Load structured state from DaemonStateStore
        from everstaff.daemon.state_store import DaemonState
        state: DaemonState = await self._state_store.load(self._agent_uuid)
        logger.debug("state loaded agent=%s goals=%d decisions=%d",
                      agent_name, len(state.goals_breakdown), len(state.recent_decisions))

        # Build context and tool registry
        ctx = ThinkToolContext(
            agent_name=agent_name,
            agent_uuid=self._agent_uuid,
            state=state,
            state_store=self._state_store,
            mem0=self._mem0,
        )
        registry = _build_think_registry(ctx)

        system_prompt = self._build_system_prompt(
            agent_name, trigger, pending_events, state, autonomy_goals,
        )
        messages: list[Message] = [
            Message(
                role="user",
                content=(
                    f"Trigger received: {trigger.type} from {trigger.source}. "
                    f"Payload: {trigger.payload}. Decide what to do."
                ),
                created_at=datetime.now(timezone.utc).isoformat(),
            ),
        ]

        # Tool loop — max _MAX_THINK_ITERATIONS rounds
        for iteration in range(_MAX_THINK_ITERATIONS):
            logger.debug("llm call agent=%s iteration=%d/%d", agent_name, iteration + 1, _MAX_THINK_ITERATIONS)
            response = await self._llm.complete(messages, registry.get_definitions(), system=system_prompt)

            if not response.tool_calls:
                logger.info("no tool call from LLM defaulting to skip agent=%s", agent_name)
                if response.content:
                    messages.append(Message(role="assistant", thinking=response.thinking, content=response.content, created_at=datetime.now(timezone.utc).isoformat()))
                ctx.decision = Decision(
                    action="skip",
                    reasoning=response.content or "No decision made",
                )
                break

            # Build a single assistant message with all tool calls
            assistant_tool_calls = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": json.dumps(tc.args)},
                }
                for tc in response.tool_calls
            ]
            messages.append(Message(
                role="assistant",
                thinking=response.thinking,
                content=response.content,
                tool_calls=assistant_tool_calls,
                created_at=datetime.now(timezone.utc).isoformat(),
            ))

            for tc in response.tool_calls:
                result = await registry.execute(tc.name, tc.args, tc.id)
                messages.append(Message(
                    role="tool",
                    content=result.content,
                    tool_call_id=tc.id,
                    created_at=datetime.now(timezone.utc).isoformat(),
                ))

            if ctx.decision is not None:
                break

        if ctx.decision is None:
            logger.warning("max iterations reached without decision agent=%s iterations=%d",
                            agent_name, _MAX_THINK_ITERATIONS)
            ctx.decision = Decision(action="skip", reasoning="Max think iterations reached")

        return ctx.decision, messages

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_system_prompt(
        self,
        agent_name: str,
        trigger: AgentEvent,
        pending_events: list[AgentEvent],
        state: Any,
        goals: list[Any],
    ) -> str:
        parts: list[str] = [
            f"You are the autonomous decision engine for agent '{agent_name}'.",
            "Your job: decide what the agent should do based on the trigger, context, and memory.",
            "",
            f"## Trigger: {trigger.type} from {trigger.source}",
        ]

        if pending_events:
            parts.append(f"\n## Pending events: {len(pending_events)}")
            for ev in pending_events[:5]:
                parts.append(f"- {ev.type} from {ev.source}")

        if goals:
            parts.append("\n## Goals:")
            for g in goals:
                parts.append(f"- [{g.priority}] {g.description}")

        if state.goals_breakdown:
            parts.append("\n## Goal breakdowns:")
            for gid, gb in state.goals_breakdown.items():
                parts.append(f"- Goal '{gid}' ({gb.completion_ratio:.0%} complete):")
                for i, sg in enumerate(gb.sub_goals):
                    parts.append(f"  {i}. [{sg.status}] {sg.description}")
                    if sg.progress_note:
                        parts.append(f"     Note: {sg.progress_note}")

        if state.recent_decisions:
            parts.append(f"\n## Recent decisions (last {min(5, len(state.recent_decisions))}):")
            for d in state.recent_decisions[-5:]:
                parts.append(f"- [{d.get('timestamp', '?')}] {d.get('action', '?')}: {d.get('task', '-')}")

        parts.append("\nUse search_memory tool to retrieve historical context from long-term memory.")
        parts.append("Call make_decision when you've decided what to do.")
        return "\n".join(parts)

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
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from everstaff.daemon.goals import GoalBreakdown, SubGoal
from everstaff.protocols import Decision, Message, ToolDefinition

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from everstaff.protocols import AgentEvent

# ---------------------------------------------------------------------------
# Tool definitions exposed to the LLM during the think loop
# ---------------------------------------------------------------------------

THINK_TOOLS: list[ToolDefinition] = [
    ToolDefinition(
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
    ),
    ToolDefinition(
        name="search_memory",
        description="Search long-term memory for relevant historical context (past episodes, patterns, insights).",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to search for"},
            },
            "required": ["query"],
        },
    ),
    ToolDefinition(
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
    ),
    ToolDefinition(
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
    ),
    ToolDefinition(
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
    ),
]

_MAX_THINK_ITERATIONS = 5


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

    def __init__(self, llm_client: Any, tracer: Any, daemon_state_store: Any, agent_uuid: str, mem0_client: Any = None, sessions_dir: str | Path | None = None, session_index: Any = None) -> None:
        self._llm = llm_client
        self._tracer = tracer
        self._state_store = daemon_state_store
        self._agent_uuid = agent_uuid
        self._mem0 = mem0_client
        self._sessions_dir: Path | None = Path(sessions_dir) if sessions_dir else None
        self._session_index = session_index

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def think(
        self,
        agent_name: str,
        trigger: AgentEvent,
        pending_events: list[AgentEvent],
        autonomy_goals: list[Any],
        parent_session_id: str,
    ) -> Decision:
        """Run the think loop and return a :class:`Decision`.

        The loop sends messages (with context) to the LLM and processes
        tool calls.  It terminates when the LLM calls ``make_decision``
        or after ``_MAX_THINK_ITERATIONS`` rounds.
        """
        logger.info("[Think:%s] Starting — trigger=%s:%s, pending=%d, goals=%d",
                     agent_name, trigger.source, trigger.type, len(pending_events), len(autonomy_goals))

        think_session_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()
        self._write_think_session(think_session_id, agent_name, parent_session_id, now)

        # Load structured state from DaemonStateStore
        from everstaff.daemon.state_store import DaemonState
        state: DaemonState = await self._state_store.load(self._agent_uuid)
        logger.debug("[Think:%s] State loaded — goals=%d, decisions=%d",
                      agent_name, len(state.goals_breakdown), len(state.recent_decisions))

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

        decision: Decision | None = None

        try:
            # Tool loop — max _MAX_THINK_ITERATIONS rounds
            for iteration in range(_MAX_THINK_ITERATIONS):
                logger.debug("[Think:%s] LLM call iteration %d/%d", agent_name, iteration + 1, _MAX_THINK_ITERATIONS)
                response = await self._llm.complete(messages, THINK_TOOLS, system=system_prompt)

                if not response.tool_calls:
                    # No tool call means the LLM declined to decide — skip.
                    logger.info("[Think:%s] No tool call from LLM — defaulting to skip", agent_name)
                    # Capture the LLM's response text before breaking
                    if response.content:
                        messages.append(Message(role="assistant", thinking=response.thinking, content=response.content, created_at=datetime.now(timezone.utc).isoformat()))
                    decision = Decision(
                        action="skip",
                        reasoning=response.content or "No decision made",
                    )
                    break

                # Build a single assistant message with all tool calls
                assistant_tool_calls = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": str(tc.args)},
                    }
                    for tc in response.tool_calls
                ]
                messages.append(Message(
                    role="assistant",
                    content=response.content,
                    tool_calls=assistant_tool_calls,
                    created_at=datetime.now(timezone.utc).isoformat(),
                ))

                decided = False
                for tc in response.tool_calls:
                    if tc.name == "make_decision":
                        decision = Decision(
                            action=tc.args.get("action", "skip"),
                            reasoning=tc.args.get("reasoning", ""),
                            task_prompt=tc.args.get("task_prompt", ""),
                            priority=tc.args.get("priority", "normal"),
                        )
                        logger.info("[Think:%s] Decision made — action=%s, priority=%s, task='%s'",
                                     agent_name, decision.action, decision.priority,
                                     decision.task_prompt[:80] if decision.task_prompt else '-')
                        messages.append(Message(
                            role="tool",
                            content=f"Decision '{decision.action}' recorded.",
                            tool_call_id=tc.id,
                            created_at=datetime.now(timezone.utc).isoformat(),
                        ))
                        decided = True

                    elif tc.name == "search_memory":
                        query = tc.args.get("query", "")
                        logger.debug("[Think:%s] Tool call: search_memory(query=%s)", agent_name, query[:80])
                        if self._mem0 is None:
                            content = "(memory not enabled)"
                        else:
                            results = await self._mem0.search(query, agent_id=agent_name)
                            if results:
                                content = "\n".join(
                                    r.get("memory", str(r)) for r in results
                                )
                            else:
                                content = "(no results)"
                        messages.append(Message(
                            role="tool",
                            content=content,
                            tool_call_id=tc.id,
                            created_at=datetime.now(timezone.utc).isoformat(),
                        ))

                    elif tc.name == "break_down_goal":
                        goal_id = tc.args["goal_id"]
                        raw_subs = tc.args.get("sub_goals", [])
                        logger.debug("[Think:%s] Tool call: break_down_goal(goal_id=%s, sub_goals=%d)",
                                     agent_name, goal_id, len(raw_subs))
                        sub_goals = [
                            SubGoal(
                                description=s["description"],
                                acceptance_criteria=s.get("acceptance_criteria", ""),
                            )
                            for s in raw_subs
                        ]
                        gb = GoalBreakdown(goal_id=goal_id, sub_goals=sub_goals)
                        state.goals_breakdown[goal_id] = gb
                        await self._state_store.save(self._agent_uuid, state)
                        messages.append(Message(
                            role="tool",
                            content=f"Goal '{goal_id}' broken into {len(sub_goals)} sub-goals.",
                            tool_call_id=tc.id,
                            created_at=datetime.now(timezone.utc).isoformat(),
                        ))

                    elif tc.name == "update_goal_progress":
                        goal_id = tc.args["goal_id"]
                        idx = tc.args["sub_goal_index"]
                        status = tc.args["status"]
                        note = tc.args.get("progress_note", "")
                        logger.debug("[Think:%s] Tool call: update_goal_progress(goal_id=%s, idx=%d, status=%s)",
                                     agent_name, goal_id, idx, status)
                        if goal_id not in state.goals_breakdown:
                            result_text = f"Error: no breakdown for goal '{goal_id}'"
                        else:
                            gb = state.goals_breakdown[goal_id]
                            if idx < 0 or idx >= len(gb.sub_goals):
                                result_text = f"Error: sub_goal_index {idx} out of range (0-{len(gb.sub_goals) - 1})"
                            else:
                                gb.sub_goals[idx].status = status
                                if note:
                                    gb.sub_goals[idx].progress_note = note
                                await self._state_store.save(self._agent_uuid, state)
                                result_text = f"Sub-goal {idx} of '{goal_id}' updated to '{status}'. Completion: {gb.completion_ratio:.0%}"
                        messages.append(Message(
                            role="tool",
                            content=result_text,
                            tool_call_id=tc.id,
                            created_at=datetime.now(timezone.utc).isoformat(),
                        ))

                    elif tc.name == "record_learning_insight":
                        args = tc.args
                        logger.debug("[Think:%s] Tool call: record_learning_insight(category=%s)",
                                     agent_name, args.get("category"))
                        if self._mem0 is None:
                            result_text = "(memory not enabled, insight not persisted)"
                        else:
                            content = f"[{args['category']}] {args['insight']} (evidence: {args['evidence']})"
                            if args.get("action"):
                                content += f" -> action: {args['action']}"
                            await self._mem0.add(
                                [{"role": "assistant", "content": content}],
                                agent_id=agent_name,
                            )
                            result_text = "Insight recorded."
                        messages.append(Message(
                            role="tool",
                            content=result_text,
                            tool_call_id=tc.id,
                            created_at=datetime.now(timezone.utc).isoformat(),
                        ))

                if decided:
                    break

            if decision is None:
                # Exhausted iterations without a decision
                logger.warning("[Think:%s] Max iterations (%d) reached without decision — defaulting to skip",
                                agent_name, _MAX_THINK_ITERATIONS)
                decision = Decision(action="skip", reasoning="Max think iterations reached")

        finally:
            # Always persist the think session, even if an exception occurred mid-loop
            final_decision = decision or Decision(action="skip", reasoning="Think loop interrupted")
            self._finish_think_session(think_session_id, agent_name, messages, final_decision, parent_session_id)

        return decision

    # ------------------------------------------------------------------
    # Think session persistence
    # ------------------------------------------------------------------

    def _write_think_session(self, session_id: str, agent_name: str, parent_session_id: str, now: str) -> None:
        """Write an initial session file for this think cycle.

        Think sessions are children of the loop session, stored under
        ``{parent}/sub_sessions/{session_id}.json``.
        """
        if self._sessions_dir is None:
            return
        sub_dir = self._sessions_dir / parent_session_id / "sub_sessions"
        try:
            sub_dir.mkdir(parents=True, exist_ok=True)
            data = {
                "session_id": session_id,
                "agent_name": agent_name,
                "status": "running",
                "created_at": now,
                "updated_at": now,
                "parent_session_id": parent_session_id,
                "root_session_id": parent_session_id,
                "metadata": {"title": "Think"},
                "messages": [],
                "hitl_requests": [],
            }
            (sub_dir / f"{session_id}.json").write_text(json.dumps(data, indent=2))
            if self._session_index is not None:
                from everstaff.session.index import IndexEntry
                self._session_index.upsert(IndexEntry(
                    id=session_id, root=parent_session_id,
                    parent=parent_session_id, agent=agent_name,
                    agent_uuid=None, status="running",
                    created_at=now, updated_at=now,
                ))
        except Exception as exc:
            logger.warning("[Think:%s] Failed to write think session %s: %s", agent_name, session_id, exc)

    def _finish_think_session(self, session_id: str, agent_name: str, messages: list[Message], decision: Decision, parent_session_id: str = "") -> None:
        """Save accumulated messages and decision into the think session."""
        if self._sessions_dir is None:
            return
        # Nested path: {parent}/sub_sessions/{session_id}.json
        if parent_session_id:
            meta_path = self._sessions_dir / parent_session_id / "sub_sessions" / f"{session_id}.json"
        else:
            meta_path = self._sessions_dir / session_id / "session.json"
        if not meta_path.exists():
            return
        try:
            data = json.loads(meta_path.read_text())
            data["messages"] = [m.to_dict() for m in messages]
            if decision.action == "execute":
                summary = f"Decision: execute\nTask: {decision.task_prompt}\nReason: {decision.reasoning}"
            else:
                summary = f"Decision: {decision.action}\nReason: {decision.reasoning}"
            data["messages"].append({"role": "assistant", "content": summary})
            data["status"] = "completed"
            data["updated_at"] = datetime.now(timezone.utc).isoformat()
            meta_path.write_text(json.dumps(data, indent=2))
            if self._session_index is not None:
                from everstaff.session.index import IndexEntry
                self._session_index.upsert(IndexEntry(
                    id=session_id, root=parent_session_id or session_id,
                    parent=parent_session_id or None, agent=agent_name,
                    agent_uuid=None, status="completed",
                    created_at=data.get("created_at", ""),
                    updated_at=data["updated_at"],
                ))
        except Exception as exc:
            logger.warning("[Think:%s] Failed to finish think session %s: %s", agent_name, session_id, exc)

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

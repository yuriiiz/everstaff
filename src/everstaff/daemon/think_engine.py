"""
ThinkEngine — Tool-based decision making for the autonomous agent.

The brain of the autonomous agent loop. When triggered, the ThinkEngine
builds context from memory (working, episodic, semantic), presents it to
an LLM along with tool definitions, and runs a tool loop until the LLM
calls ``make_decision`` to produce a :class:`Decision`.

Tools available to the LLM during thinking:
- ``make_decision`` — commit to an action (execute / skip / defer)
- ``recall_semantic_detail`` — read a specific semantic memory topic
- ``recall_recent_episodes`` — query recent episodic memory
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from everstaff.protocols import Decision, Message, ToolDefinition

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from everstaff.protocols import AgentEvent, Episode, WorkingState

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
        name="recall_semantic_detail",
        description="Read a specific semantic memory topic for more detail.",
        parameters={
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "The topic to read",
                },
            },
            "required": ["topic"],
        },
    ),
    ToolDefinition(
        name="recall_recent_episodes",
        description="Recall recent episodes from episodic memory.",
        parameters={
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "How many days back to look",
                    "default": 1,
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filter by tags",
                },
            },
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
    memory:
        Any object satisfying the ``MemoryStore`` protocol.
    tracer:
        Any object satisfying the ``TracingBackend`` protocol.
    """

    def __init__(self, llm_client: Any, memory: Any, tracer: Any, sessions_dir: str | Path | None = None) -> None:
        self._llm = llm_client
        self._memory = memory
        self._tracer = tracer
        self._sessions_dir: Path | None = Path(sessions_dir) if sessions_dir else None

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

        # Gather context from memory layers
        working: WorkingState = await self._memory.working_load(agent_name)
        episodes: list[Episode] = await self._memory.episode_query(
            agent_name, days=1, limit=10,
        )
        topics: list[str] = await self._memory.semantic_list(agent_name)
        logger.debug("[Think:%s] Memory context — working_items=%d, episodes=%d, topics=%s",
                      agent_name, len(working.pending_items), len(episodes), topics)

        system_prompt = self._build_system_prompt(
            agent_name, trigger, pending_events, working, episodes, topics, autonomy_goals,
        )
        messages: list[Message] = [
            Message(
                role="user",
                content=(
                    f"Trigger received: {trigger.type} from {trigger.source}. "
                    f"Payload: {trigger.payload}. Decide what to do."
                ),
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
                        messages.append(Message(role="assistant", content=response.content))
                    decision = Decision(
                        action="skip",
                        reasoning=response.content or "No decision made",
                    )
                    break

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
                        # Capture assistant tool call + tool result to complete the exchange
                        messages.append(Message(
                            role="assistant",
                            content=response.content,
                            tool_calls=[{
                                "id": tc.id,
                                "type": "function",
                                "function": {"name": tc.name, "arguments": str(tc.args)},
                            }],
                        ))
                        messages.append(Message(
                            role="tool",
                            content=f"Decision '{decision.action}' recorded.",
                            tool_call_id=tc.id,
                        ))
                        decided = True
                        break

                if tc.name == "recall_semantic_detail":
                    topic = tc.args.get("topic", "index")
                    logger.debug("[Think:%s] Tool call: recall_semantic_detail(topic=%s)", agent_name, topic)
                    content = await self._memory.semantic_read(agent_name, topic)
                    messages.append(Message(
                        role="assistant",
                        content=None,
                        tool_calls=[{
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": str(tc.args),
                            },
                        }],
                    ))
                    messages.append(Message(
                        role="tool",
                        content=content or "(empty)",
                        tool_call_id=tc.id,
                    ))

                elif tc.name == "recall_recent_episodes":
                    days = tc.args.get("days", 1)
                    tags = tc.args.get("tags")
                    logger.debug("[Think:%s] Tool call: recall_recent_episodes(days=%s, tags=%s)", agent_name, days, tags)
                    eps = await self._memory.episode_query(
                        agent_name, days=days, tags=tags,
                    )
                    ep_text = "\n".join(
                        f"- [{e.timestamp}] {e.trigger}: {e.action} -> {e.result}"
                        for e in eps
                    ) or "(no episodes)"
                    messages.append(Message(
                        role="assistant",
                        content=None,
                        tool_calls=[{
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": str(tc.args),
                            },
                        }],
                    ))
                    messages.append(Message(
                        role="tool",
                        content=ep_text,
                        tool_call_id=tc.id,
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
            self._finish_think_session(think_session_id, agent_name, messages, final_decision)

        return decision

    # ------------------------------------------------------------------
    # Think session persistence
    # ------------------------------------------------------------------

    def _write_think_session(self, session_id: str, agent_name: str, parent_session_id: str, now: str) -> None:
        """Write an initial session.json for this think cycle."""
        if self._sessions_dir is None:
            return
        session_dir = self._sessions_dir / session_id
        try:
            session_dir.mkdir(parents=True, exist_ok=True)
            data = {
                "session_id": session_id,
                "agent_name": agent_name,
                "status": "running",
                "created_at": now,
                "updated_at": now,
                "parent_session_id": parent_session_id,
                "metadata": {"title": "Think"},
                "messages": [],
                "hitl_requests": [],
            }
            (session_dir / "session.json").write_text(json.dumps(data, indent=2))
        except Exception as exc:
            logger.warning("[Think:%s] Failed to write think session %s: %s", agent_name, session_id, exc)

    def _finish_think_session(self, session_id: str, agent_name: str, messages: list[Message], decision: Decision) -> None:
        """Save accumulated messages and decision into the think session."""
        if self._sessions_dir is None:
            return
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
        working: WorkingState,
        episodes: list[Episode],
        topics: list[str],
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

        if working.pending_items:
            parts.append(f"\n## Pending items: {working.pending_items}")

        if working.goals_progress:
            parts.append(f"\n## Goal progress: {working.goals_progress}")

        if episodes:
            parts.append(f"\n## Recent episodes ({len(episodes)}):")
            for ep in episodes[-5:]:
                parts.append(f"- [{ep.timestamp}] {ep.action} -> {ep.result}")

        if topics:
            parts.append(f"\n## Semantic memory topics: {topics}")
            parts.append("Use recall_semantic_detail tool to read any topic.")

        parts.append("\nCall make_decision when you've decided what to do.")
        return "\n".join(parts)

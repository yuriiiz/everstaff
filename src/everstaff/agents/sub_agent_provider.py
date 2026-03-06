"""DefaultSubAgentProvider — owns a single DelegateTaskTool for all sub-agents."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from everstaff.protocols import Tool, CancellationEvent, Hook
    from everstaff.schema.agent_spec import SubAgentSpec
    from everstaff.builder.environment import RuntimeEnvironment


class DefaultSubAgentProvider:
    """Provides a single DelegateTaskTool to the ToolRegistry."""

    def __init__(
        self,
        specs: list[SubAgentSpec],
        env: RuntimeEnvironment,
        parent_model_id: str | None = None,
        parent_session_id: str | None = None,
        parent_cancellation: CancellationEvent | None = None,
        caller_span_id: str | None = None,
        parent_hooks: list[Hook] | None = None,
        root_session_id: str | None = None,
    ) -> None:
        from everstaff.agents.delegate_task_tool import DelegateTaskTool
        self._env = env
        self._parent_model_id = parent_model_id
        self._parent_session_id = parent_session_id
        self._parent_cancellation = parent_cancellation
        self._caller_span_id = caller_span_id
        self._parent_hooks = parent_hooks
        self._root_session_id = root_session_id
        self._tool: DelegateTaskTool | None = None
        if specs:
            self._tool = DelegateTaskTool(
                specs=specs,
                env=env,
                parent_model_id=parent_model_id,
                parent_session_id=parent_session_id,
                parent_cancellation=parent_cancellation,
                caller_span_id=caller_span_id,
                parent_hooks=parent_hooks,
                root_session_id=root_session_id,
            )

    def get_tools(self) -> list[Tool]:
        return [self._tool] if self._tool is not None else []

    def get_prompt_injection(self) -> str:
        if self._tool is None:
            return ""
        lines = ["## Available Sub-Agents", ""]
        for name, spec in sorted(self._tool._registry.items()):
            lines.append(f"- **{name}**: {spec.description}")
        lines.append("")
        lines.append("### Sub-Agent Delegation Rules")
        lines.append("")
        lines.append(
            "When a task should be handled by a sub-agent, you MUST call "
            "the `delegate_task_to_subagent` tool. NEVER describe what a sub-agent should do "
            "in your response text without actually delegating via the tool. "
            "If a sub-agent is suited for the task, delegate it — do not attempt "
            "the work yourself."
        )
        lines.append("")
        lines.append("### Sub-Agent HITL Escalation Rules")
        lines.append("")
        lines.append(
            "When a sub-agent returns a `[SUB_AGENT_HITL]` message, the sub-agent is paused and "
            "waiting for human input. You MUST handle this as a **two-step round-trip** — NEVER just "
            "describe or narrate the HITL request in your response text.\n"
            "\n"
            "**Step 1 — Decide how to answer the sub-agent's question:**\n"
            "\n"
            "- **Option A — Answer it yourself**: If you have enough context, go directly to Step 2.\n"
            "- **Option B — Escalate to the human**: If you cannot answer, call `request_human_input` "
            "to ask the human. Include the sub-agent's question and context. Then proceed to Step 2 "
            "when the human responds.\n"
            "\n"
            "**Step 2 — Relay the answer back to the sub-agent (MANDATORY):**\n"
            "\n"
            "You MUST call `delegate_task_to_subagent` with ALL of these parameters:\n"
            "- `agent_name`: the sub-agent's name from the HITL message\n"
            "- `prompt`: a brief summary of the context or instruction\n"
            "- `resume_session_id`: the `child_session_id` from the `[SUB_AGENT_HITL]` message\n"
            "- `hitl_response`: an object with `decision` (the answer, e.g. \"approved\", \"rejected\", "
            "or free text) and optional `comment`\n"
            "\n"
            "**CRITICAL**: Step 2 is required even if the human rejected the request. Without calling "
            "`delegate_task_to_subagent` with `resume_session_id` and `hitl_response`, the sub-agent "
            "will remain stuck in `waiting_for_human` state forever. You must ALWAYS relay the decision back."
        )
        return "\n".join(lines)

    def register(self, name: str, spec: SubAgentSpec) -> None:
        """Dynamically add a new sub-agent at runtime (used by bootstrap)."""
        if self._tool is None:
            if self._env is None:
                import logging
                logging.getLogger(__name__).warning(
                    "register(%s) called on empty DefaultSubAgentProvider — no env available, skipping",
                    name,
                )
                return
            from everstaff.agents.delegate_task_tool import DelegateTaskTool
            self._tool = DelegateTaskTool(
                specs=[],
                env=self._env,
                parent_model_id=self._parent_model_id,
                parent_session_id=self._parent_session_id,
                parent_cancellation=self._parent_cancellation,
                caller_span_id=self._caller_span_id,
                parent_hooks=self._parent_hooks,
                root_session_id=self._root_session_id,
            )
        self._tool.register(name, spec)

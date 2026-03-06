"""WorkflowSubAgentFactory — spawns independent AgentRuntime per workflow task."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from everstaff.builder.agent_builder import AgentBuilder

if TYPE_CHECKING:
    from everstaff.builder.environment import RuntimeEnvironment
    from everstaff.protocols import CancellationEvent
    from everstaff.schema.agent_spec import SubAgentSpec


class WorkflowSubAgentFactory:
    """Creates a fresh AgentRuntime for each workflow task assignment.

    Each call to run() produces an independent session with its own session_id,
    memory, and tracer — but shares parent_cancellation so stop propagates.
    """

    def __init__(
        self,
        available_agents: dict[str, SubAgentSpec],
        env: RuntimeEnvironment,
        parent_session_id: str,
        parent_cancellation: CancellationEvent,
        parent_model_id: str,
        root_session_id: str | None = None,
    ) -> None:
        self._agents = available_agents
        self._env = env
        self._parent_session_id = parent_session_id
        self._cancellation = parent_cancellation
        self._parent_model_id = parent_model_id
        self._root_session_id = root_session_id

    async def run(self, agent_name: str, prompt: str) -> str:
        """Run a sub-agent and return its text output (stats discarded)."""
        output, _ = await self.run_with_stats(agent_name, prompt)
        return output

    async def run_with_stats(self, agent_name: str, prompt: str) -> "tuple[str, Any]":
        """Run a sub-agent and return (output, SessionStats | None).

        The stats allow callers to accumulate sub-agent token usage into the
        parent's children_calls.
        """
        spec = self._agents.get(agent_name)
        if spec is None:
            return f"[Error] Unknown agent: '{agent_name}'. Available: {list(self._agents)}", None

        # Convert SubAgentSpec to AgentSpec (use to_agent_spec() if available, else construct)
        try:
            agent_spec = spec.to_agent_spec()
        except AttributeError:
            from everstaff.schema.agent_spec import AgentSpec
            agent_spec = AgentSpec(
                agent_name=spec.name,
                instructions=getattr(spec, "instructions", ""),
            )

        runtime, ctx = await AgentBuilder(
            agent_spec,
            self._env,
            parent_model_id=self._parent_model_id,
            parent_session_id=self._parent_session_id,
            parent_cancellation=self._cancellation,
            root_session_id=self._root_session_id,
        ).build()
        try:
            output = await runtime.run(prompt)
            child_stats = getattr(runtime, "stats", None)
            return output, child_stats
        finally:
            await ctx.aclose()

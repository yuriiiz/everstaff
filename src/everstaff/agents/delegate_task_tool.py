from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from everstaff.protocols import CancellationEvent, HookContext, HumanApprovalRequired, ToolDefinition, ToolResult
from everstaff.builder.agent_builder import AgentBuilder
from everstaff.hitl.resolve import resolve_hitl as canonical_resolve

if TYPE_CHECKING:
    from everstaff.builder.environment import RuntimeEnvironment
    from everstaff.protocols import Hook
    from everstaff.schema.agent_spec import SubAgentSpec

logger = logging.getLogger(__name__)


class DelegateTaskTool:
    """
    Single tool that delegates to any configured sub-agent by name.
    Replaces the old per-agent SubAgentTool pattern with 1 tool + internal routing.
    Parent runtime has zero knowledge of sub-agent machinery.
    """

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
        self._registry: dict[str, SubAgentSpec] = {s.name: s for s in specs}
        self._env = env
        self._parent_model_id = parent_model_id
        self._parent_session_id = parent_session_id
        self._parent_cancellation = parent_cancellation or CancellationEvent()
        self._caller_span_id = caller_span_id
        self._parent_hooks: list[Hook] = parent_hooks or []
        self._root_session_id = root_session_id

    def register(self, name: str, spec: SubAgentSpec) -> None:
        """Dynamically add a new sub-agent. enum updates automatically (definition is a property)."""
        self._registry[name] = spec

    @property
    def definition(self) -> ToolDefinition:
        agent_names = sorted(self._registry.keys())
        return ToolDefinition(
            name="delegate_task_to_subagent",
            description=(
                "Delegate a task to a specialized sub-agent by name. "
                "You MUST call this tool to assign work to sub-agents. "
                "NEVER describe or simulate sub-agent work in your response text — always delegate via this tool."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "agent_name": {
                        "type": "string",
                        "enum": agent_names,
                        "description": "The sub-agent to delegate to.",
                    },
                    "prompt": {
                        "type": "string",
                        "description": "The task prompt to send to the agent.",
                    },
                    "resume_session_id": {
                        "type": "string",
                        "description": "Session ID of a paused child to resume after HITL resolution.",
                    },
                    "hitl_response": {
                        "type": "object",
                        "description": "Human decision to resolve the child's pending HITL request.",
                    },
                },
                "required": ["agent_name", "prompt"],
            },
        )

    def _hook_ctx(self, agent_name: str) -> HookContext:
        session_id = self._parent_session_id or ""
        return HookContext(session_id=session_id, agent_name=agent_name)

    async def _fire_subagent_start(self, agent_name: str, prompt: str) -> str:
        ctx = self._hook_ctx(agent_name)
        for hook in self._parent_hooks:
            try:
                result = await hook.on_subagent_start(ctx, agent_name, prompt)
                if isinstance(result, str):
                    prompt = result
            except Exception:
                logger.debug("on_subagent_start hook %r raised; swallowing", hook, exc_info=True)
        return prompt

    async def _fire_subagent_end(self, agent_name: str, result: str) -> None:
        ctx = self._hook_ctx(agent_name)
        for hook in self._parent_hooks:
            try:
                await hook.on_subagent_end(ctx, agent_name, result)
            except Exception:
                logger.debug("on_subagent_end hook %r raised; swallowing", hook, exc_info=True)

    @staticmethod
    def _format_hitl_escalation(
        agent_name: str,
        child_session_id: str,
        requests: "list[Any] | Any",
    ) -> str:
        """Format a structured HITL escalation message for the parent agent."""
        if not isinstance(requests, list):
            requests = [requests]
        lines = [
            "[SUB_AGENT_HITL]",
            f"agent_name: {agent_name}",
            f"child_session_id: {child_session_id}",
            f"hitl_request_count: {len(requests)}",
        ]
        for i, request in enumerate(requests):
            lines.append(f"--- request {i + 1} ---")
            lines.append(f"hitl_id: {request.hitl_id}")
            lines.append(f"type: {request.type}")
            lines.append(f"prompt: {request.prompt}")
            if request.options:
                lines.append(f"options: {request.options}")
            if request.context:
                lines.append(f"context: {request.context}")
        return "\n".join(lines)


    async def _resolve_child_hitl(
        self,
        session_id: str,
        hitl_response: dict[str, Any],
    ) -> None:
        """Resolve child HITL via canonical function, then insert tool messages for resume."""
        import json
        from everstaff.api.sessions import _format_decision_message
        from everstaff.session.index import SessionIndex

        file_store = self._env.build_file_store()
        hitl_id = hitl_response.get("hitl_id", "")
        decision = hitl_response.get("decision", "")
        comment = hitl_response.get("comment")

        session_path = SessionIndex.session_relpath(session_id, self._root_session_id)

        # Step 1: Use canonical resolve for individual HITL (if hitl_id provided)
        if hitl_id:
            try:
                await canonical_resolve(
                    session_id=session_id,
                    hitl_id=hitl_id,
                    decision=decision,
                    comment=comment,
                    file_store=file_store,
                    root_session_id=self._root_session_id,
                )
            except Exception:
                pass  # Swallow -- legacy callers may pass invalid hitl_id
        else:
            # Legacy path: resolve ALL pending HITLs in the session
            try:
                raw = await file_store.read(session_path)
                session_data = json.loads(raw.decode())
            except Exception:
                return
            for item in session_data.get("hitl_requests", []):
                if item.get("status") == "pending":
                    try:
                        await canonical_resolve(
                            session_id=session_id,
                            hitl_id=item["hitl_id"],
                            decision=decision,
                            comment=comment,
                            file_store=file_store,
                            root_session_id=self._root_session_id,
                        )
                    except Exception:
                        pass

        # Step 2: Insert tool messages for resume
        try:
            raw = await file_store.read(session_path)
            session_data = json.loads(raw.decode())
        except Exception:
            return

        messages_data = session_data.get("messages", [])
        for item in session_data.get("hitl_requests", []):
            if item.get("status") == "resolved" and item.get("response"):
                req = item.get("request", {})
                resp = item.get("response", {})
                dtxt = _format_decision_message(req, resp.get("decision", ""), resp.get("comment"))
                tc_id = item.get("tool_call_id", "")
                messages_data.append({"role": "tool", "content": dtxt, "tool_call_id": tc_id})

        session_data["messages"] = messages_data
        await file_store.write(
            session_path,
            json.dumps(session_data, ensure_ascii=False, indent=2).encode(),
        )

    async def _resume_child(
        self,
        agent_name: str,
        prompt: str,
        resume_session_id: str,
        hitl_response: dict[str, Any],
    ) -> ToolResult:
        """Resolve the child's HITL request and re-run the child session.

        1. Validate the session exists and has messages.
        2. Write the human's decision into the child's session.json (HITL status + tool messages).
        3. Build a runtime that reuses the child's session_id so it loads previous context.
        4. Run with input_text=None so the LLM continues from the HITL tool response.
        """
        import json
        from everstaff.session.index import SessionIndex
        session_path = SessionIndex.session_relpath(resume_session_id, self._root_session_id)
        try:
            file_store = self._env.build_file_store()
            raw = await file_store.read(session_path)
            session_data = json.loads(raw.decode())
            if not session_data.get("messages"):
                return ToolResult(
                    tool_call_id="",
                    content=(
                        f"Error: session '{resume_session_id}' has no messages. "
                        "Provide a valid child_session_id from a [SUB_AGENT_HITL] message."
                    ),
                    is_error=True,
                )
        except NotImplementedError:
            pass  # Test / non-file-store environment — skip existence check
        except FileNotFoundError:
            return ToolResult(
                tool_call_id="",
                content=(
                    f"Error: session '{resume_session_id}' not found. "
                    "Provide a valid child_session_id from a [SUB_AGENT_HITL] message."
                ),
                is_error=True,
            )
        except Exception:
            pass  # Other I/O errors — let _resolve_child_hitl handle them

        await self._resolve_child_hitl(resume_session_id, hitl_response)

        spec = self._registry[agent_name]
        child_spec = spec.to_agent_spec()

        runtime, child_ctx = await AgentBuilder(
            child_spec,
            self._env,
            parent_model_id=self._parent_model_id,
            parent_session_id=self._parent_session_id,
            parent_cancellation=self._parent_cancellation,
            caller_span_id=self._caller_span_id,
            session_id=resume_session_id,
            root_session_id=self._root_session_id,
        ).build()

        try:
            # input_text=None: the LLM will see the existing messages (including
            # the freshly-appended HITL tool response) and continue naturally.
            response = await runtime.run(None)
        except HumanApprovalRequired as exc:
            child_session_id = getattr(child_ctx, "session_id", "")
            # Set origin metadata on each request
            for req in exc.requests:
                if not req.origin_session_id:
                    req.origin_session_id = child_session_id
                if not req.origin_agent_name:
                    req.origin_agent_name = agent_name
            child_stats = getattr(runtime, "stats", None)
            content = self._format_hitl_escalation(agent_name, child_session_id, exc.requests)
            result = ToolResult(tool_call_id="", content=content, is_error=False,
                                child_stats=child_stats)
            result._child_hitl_requests = list(exc.requests)
            return result

        child_stats = getattr(runtime, "stats", None)

        await self._fire_subagent_end(agent_name, response)

        return ToolResult(tool_call_id="", content=response, child_stats=child_stats)

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        if self._parent_cancellation.is_cancelled:
            return ToolResult(tool_call_id="", content="[Stopped]", is_error=False)

        agent_name = args.get("agent_name", "")
        prompt = args.get("prompt", "")

        spec = self._registry.get(agent_name)
        if spec is None:
            known = ", ".join(sorted(self._registry.keys()))
            return ToolResult(
                tool_call_id="",
                content=f"Unknown agent '{agent_name}'. Available: {known}",
                is_error=True,
            )

        # Resume path: resolve child HITL and re-run
        resume_session_id = args.get("resume_session_id")
        hitl_response = args.get("hitl_response")
        if resume_session_id and hitl_response:
            return await self._resume_child(agent_name, prompt, resume_session_id, hitl_response)

        prompt = await self._fire_subagent_start(agent_name, prompt)

        child_spec = spec.to_agent_spec()
        runtime, child_ctx = await AgentBuilder(
            child_spec,
            self._env,
            parent_model_id=self._parent_model_id,
            parent_session_id=self._parent_session_id,
            parent_cancellation=self._parent_cancellation,
            caller_span_id=self._caller_span_id,
            root_session_id=self._root_session_id,
        ).build()

        try:
            response = await runtime.run(prompt)
        except HumanApprovalRequired as exc:
            child_session_id = getattr(child_ctx, "session_id", "")
            # Set origin metadata on each request
            for req in exc.requests:
                if not req.origin_session_id:
                    req.origin_session_id = child_session_id
                if not req.origin_agent_name:
                    req.origin_agent_name = agent_name
            child_stats = getattr(runtime, "stats", None)
            content = self._format_hitl_escalation(agent_name, child_session_id, exc.requests)
            result = ToolResult(tool_call_id="", content=content, is_error=False,
                                child_stats=child_stats)
            result._child_hitl_requests = list(exc.requests)
            return result

        child_stats = getattr(runtime, "stats", None)

        await self._fire_subagent_end(agent_name, response)

        return ToolResult(tool_call_id="", content=response, child_stats=child_stats)

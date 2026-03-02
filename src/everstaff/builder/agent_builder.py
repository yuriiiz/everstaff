from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from everstaff.builder.environment import RuntimeEnvironment
from everstaff.core.context import AgentContext
from everstaff.core.runtime import AgentRuntime
from everstaff.tools.pipeline import ToolCallPipeline
from everstaff.tools.stages import ExecutionStage, PermissionStage
from everstaff.schema.agent_spec import AgentSpec
from everstaff.tools.default_registry import DefaultToolRegistry
from everstaff.protocols import AgentEvent, CancellationEvent


class AgentBuilder:
    """
    Single place that knows how to assemble AgentContext from AgentSpec + RuntimeEnvironment.
    AgentRuntime has no knowledge of this class.
    """

    def __init__(
        self,
        spec: AgentSpec,
        env: RuntimeEnvironment,
        parent_model_id: str | None = None,
        parent_session_id: str | None = None,
        parent_cancellation: CancellationEvent | None = None,
        hooks: list[Any] | None = None,
        caller_span_id: str | None = None,
        session_id: str | None = None,
        trigger: "AgentEvent | None" = None,
    ) -> None:
        self._spec = spec
        self._env = env
        self._parent_model_id = parent_model_id
        self._parent_session_id = parent_session_id
        self._parent_cancellation = parent_cancellation
        self._hooks = hooks or []
        self._caller_span_id = caller_span_id
        self._session_id = session_id
        self._trigger = trigger

    def _resolve_model(self) -> str:
        """Resolve the concrete LiteLLM model string for this agent.

        Priority:
        1. spec.model_override — explicit override takes precedence
        2. spec.adviced_model_kind == "inherit" → use parent model id
        3. spec.adviced_model_kind → looked up in config.model_mappings
        """
        if self._spec.model_override:
            return self._spec.model_override

        if self._spec.adviced_model_kind == "inherit":
            if self._parent_model_id:
                return self._parent_model_id
            # fallthrough: defensive, shouldn't happen at top level

        kind = self._spec.adviced_model_kind
        if kind == "inherit":
            kind = "smart"  # defensive fallback when no parent provided
        return self._env.config.resolve_model(kind).model_id

    def _build_system_prompt(self) -> str | None:
        parts = []
        # 1. Project context
        try:
            from everstaff.project_context import ProjectContextLoader
            loader = ProjectContextLoader(self._env.project_root())
            proj = loader.load()
            if proj:
                parts.append(proj)
        except Exception as exc:
            logger.debug("ProjectContextLoader unavailable: %s", exc)
        # 2. Agent instructions
        if self._spec.instructions:
            parts.append(self._spec.instructions)
        return "\n\n".join(parts) if parts else None

    async def build(self) -> tuple[AgentRuntime, AgentContext]:
        # 0. Generate session_id first so it can be passed to tracer
        session_id = self._session_id or self._env.new_session_id()
        workdir = self._env.working_dir(session_id)
        model_id = self._resolve_model()

        # Resolve cancellation FIRST so all children share the same event
        cancellation = self._parent_cancellation if self._parent_cancellation is not None else CancellationEvent()

        # 1. Build independent modules in parallel
        memory, tracer = await asyncio.gather(
            self._build_memory(session_id),
            self._build_tracer(session_id),
        )
        tool_registry = self._build_tool_registry(workdir)
        skill_provider = await self._build_skill_provider()
        knowledge_provider = await self._build_knowledge_provider()
        sub_agent_provider = self._build_sub_agent_provider(model_id, workdir, session_id, cancellation)
        mcp_provider = await self._build_mcp_provider()

        # Collect provider tool names so they can be auto-injected into the allow list.
        def _tool_name(t) -> str:
            return t.name if hasattr(t, "name") else t.definition.name

        provider_tool_names = [
            _tool_name(t)
            for provider in (skill_provider, knowledge_provider, sub_agent_provider, mcp_provider)
            for t in provider.get_tools()
        ]
        permissions = self._build_permissions(extra_allow=provider_tool_names)

        # 1b. Register tools from all providers into the shared registry
        for tool in sub_agent_provider.get_tools():
            tool_registry.register(tool)
        for tool in skill_provider.get_tools():
            tool_registry.register(tool)
        for tool in knowledge_provider.get_tools():
            tool_registry.register(tool)
        for tool in mcp_provider.get_tools():
            tool_registry.register(tool)

        # 1c. Register DAGTool if workflow is configured
        dag_tool = self._build_workflow_tool(session_id, model_id, cancellation, tracer, memory)
        if dag_tool:
            tool_registry.register_native(dag_tool)

        # 2. Assemble pipeline (order is explicit and intentional)
        pipeline = ToolCallPipeline([
            PermissionStage(permissions),
            ExecutionStage(tool_registry),
        ])

        # Resolve sessions_dir from environment (may be None for non-CLI envs)
        sessions_dir = self._env.sessions_dir() if callable(getattr(self._env, "sessions_dir", None)) else None

        # Resolve file_store from environment (may raise NotImplementedError for non-CLI envs)
        try:
            file_store = self._env.build_file_store()
        except NotImplementedError:
            file_store = None

        # 3. Build context
        context = AgentContext(
            # Required
            tool_registry=tool_registry,
            memory=memory,
            tool_pipeline=pipeline,

            # Basic
            agent_name=self._spec.agent_name,
            agent_uuid=self._spec.uuid,
            system_prompt=self._build_system_prompt(),
            permissions=permissions,
            skill_provider=skill_provider,
            knowledge_provider=knowledge_provider,
            sub_agent_provider=sub_agent_provider,
            mcp_provider=mcp_provider,

            # Metadata & infrastructure
            session_id=session_id,
            parent_session_id=self._parent_session_id,
            tracer=tracer,
            hooks=self._hooks,
            cancellation=cancellation,
            caller_span_id=self._caller_span_id,

            # Bootstrap support
            sessions_dir=sessions_dir,
            file_store=file_store,

            # LLM limits for metadata persistence
            max_tokens=getattr(self._spec, "max_tokens", None),

            # Event that triggered this session (e.g. from scheduler)
            trigger=self._trigger,
        )

        # Wire env reference for dynamic agent/skill registration
        context._env = self._env
        # Wire channel_manager from environment (set by API/CLI layer)
        if self._env.channel_manager is not None:
            context.channel_manager = self._env.channel_manager
            # Wire channel_manager + session_id into HITL tool for notify-type broadcasts
            from everstaff.tools.hitl_tool import RequestHumanInputTool
            for tool in tool_registry._tools.values():
                if isinstance(tool, RequestHumanInputTool):
                    tool._channel_manager = self._env.channel_manager
                    tool._session_id = session_id

        # 4. Build LLM client and runtime
        # Forward AgentSpec overrides (max_tokens, temperature) to LiteLLM kwargs.
        llm_kwargs: dict = {}
        if getattr(self._spec, "max_tokens", None) is not None:
            llm_kwargs["max_tokens"] = self._spec.max_tokens
        if getattr(self._spec, "temperature", None) is not None:
            llm_kwargs["temperature"] = self._spec.temperature
        llm_client = self._env.build_llm_client(model_id, **llm_kwargs)

        # 5. Register bootstrap tools only when explicitly enabled
        if getattr(self._spec, "enable_bootstrap", False):
            from everstaff.tools.bootstrap import CreateAgentTool
            from everstaff.skills.create_skill_tool import CreateSkillTool

            bootstrap_tool = CreateAgentTool(ctx=context, llm=llm_client)
            tool_registry.register_native(bootstrap_tool)

            # Filter out package builtin dir (read-only) from install dirs
            install_dirs = list(self._env.config.skills_dirs)
            try:
                import everstaff as _pkg
                builtin = str(Path(_pkg.__file__).parent / "builtin_skills")
                install_dirs = [d for d in install_dirs if str(Path(d).expanduser().resolve()) != str(Path(builtin).resolve())]
            except Exception:
                pass

            create_skill_tool = CreateSkillTool(install_dirs=install_dirs)
            tool_registry.register_native(create_skill_tool)

        return AgentRuntime(context=context, llm_client=llm_client), context

    async def _build_memory(self, session_id: str = ""):
        # Resolve the model's max_tokens so the memory store can set a
        # context-aware compression threshold (0.7 × max_tokens).
        kind = self._spec.adviced_model_kind
        if kind == "inherit":
            kind = "smart"
        try:
            model_max_tokens = self._env.config.resolve_model(kind).max_tokens
        except Exception:
            model_max_tokens = None
        return self._env.build_memory_store(max_tokens=model_max_tokens)

    async def _build_tracer(self, session_id: str = ""):
        return self._env.build_tracer(session_id)

    def _build_permissions(self, extra_allow: list[str] | None = None):
        from everstaff.permissions.rule_checker import RuleBasedChecker
        from everstaff.permissions.chained import ChainedPermissionChecker

        global_cfg = self._env.config.permissions
        # Global checker: strict=False — only deny rules apply globally,
        # no whitelist restriction at this level.
        global_checker = RuleBasedChecker(
            allow=[],
            deny=global_cfg.deny,
            strict=False,
        )

        # Agent checker: always strict=True (whitelist mode).
        # AgentSpec.permissions always has a PermissionConfig default (never None).
        agent_cfg = self._spec.permissions
        allow = list(agent_cfg.allow)
        deny = list(agent_cfg.deny)

        # Auto-inject spec.tools into allow — tools explicitly listed by the user are always permitted,
        # unless they are explicitly denied (deny wins over allow).
        for t in (getattr(self._spec, "tools", None) or []):
            if t not in allow and t not in deny:
                allow.append(t)

        # Auto-inject provider tools (use_skill, search_knowledge, MCP tools, etc.)
        for t in (extra_allow or []):
            if t not in allow and t not in deny:
                allow.append(t)

        # Unconditionally inject framework tools when their feature is enabled.
        # Framework tools must always be reachable regardless of the allow list state.
        hitl_mode = getattr(self._spec, "hitl_mode", "on_request")
        if getattr(self._spec, "sub_agents", None) and "delegate_task_to_subagent" not in allow and "delegate_task_to_subagent" not in deny:
            allow.append("delegate_task_to_subagent")
        if hitl_mode != "never" and "request_human_input" not in allow and "request_human_input" not in deny:
            allow.append("request_human_input")
        if getattr(self._spec, "workflow", None) and "write_workflow_plan" not in allow and "write_workflow_plan" not in deny:
            allow.append("write_workflow_plan")
        if getattr(self._spec, "enable_bootstrap", False):
            for tool_name in ("create_agent", "create_skill"):
                if tool_name not in allow and tool_name not in deny:
                    allow.append(tool_name)

        agent_checker = RuleBasedChecker(
            allow=allow,
            deny=deny,
            strict=True,
        )

        # If global has no rules, skip chaining for efficiency
        if not global_cfg.deny:
            return agent_checker

        return ChainedPermissionChecker(global_checker, agent_checker)

    def _build_tool_registry(self, workdir: Path | None = None) -> DefaultToolRegistry:
        reg = DefaultToolRegistry()
        tool_names = list(getattr(self._spec, "tools", None) or [])

        # Separate framework tools from regular tools
        framework_tools, regular_tools = self._split_framework_tools(tool_names)

        # Register regular tools via ToolLoader
        if regular_tools:
            from everstaff.tools.loader import ToolLoader
            loader = ToolLoader(self._env.config.tools_dirs)
            for t in loader.load(regular_tools, workdir=workdir):
                reg.register_native(t)

        # Register framework tools (builtin-only)
        for tool in framework_tools:
            reg.register_native(tool)

        # Register HITL tool unless explicitly disabled
        hitl_mode = getattr(self._spec, "hitl_mode", "on_request")
        if hitl_mode != "never":
            from everstaff.tools.hitl_tool import RequestHumanInputTool
            reg.register_native(RequestHumanInputTool(mode=hitl_mode))
        return reg

    def _split_framework_tools(self, tool_names: list[str]) -> tuple[list, list[str]]:
        """Separate framework tools from regular tools.

        Framework tools require env injection and are only available to builtin agents.
        Returns (framework_tool_instances, remaining_tool_names).
        """
        from everstaff.tools.reconcile import SystemReconcileTool

        _FRAMEWORK_TOOL_FACTORIES = {
            "system_reconcile": lambda env: SystemReconcileTool(env),
        }

        framework = []
        regular = []
        source = getattr(self._spec, "source", "custom")

        for name in tool_names:
            factory = _FRAMEWORK_TOOL_FACTORIES.get(name)
            if factory is not None:
                if source != "builtin":
                    logger.warning(
                        "Framework tool '%s' is only available to builtin agents (source=%s), skipping",
                        name, source,
                    )
                    continue
                framework.append(factory(self._env))
            else:
                regular.append(name)

        return framework, regular

    async def _build_skill_provider(self):
        if not self._spec.skills:
            from everstaff.nulls import NullSkillProvider
            return NullSkillProvider()
        try:
            from everstaff.skills.manager import SkillManager
            # Merge built-in skills dir (last so user dirs take precedence via first-dir-wins)
            skills_dirs = list(self._env.config.skills_dirs)
            try:
                import everstaff as _pkg
                builtin = str(Path(_pkg.__file__).parent / "builtin_skills")
                if builtin not in skills_dirs:
                    skills_dirs.append(builtin)
            except Exception:
                pass
            return SkillManager(
                skills_dirs=skills_dirs,
                active_skill_names=self._spec.skills,
            )
        except Exception as exc:
            logger.debug("SkillManager unavailable for skills %s: %s", self._spec.skills, exc)
            from everstaff.nulls import NullSkillProvider
            return NullSkillProvider()

    async def _build_knowledge_provider(self):
        if not getattr(self._spec, "knowledge_base", None):
            from everstaff.nulls import NullKnowledgeProvider
            return NullKnowledgeProvider()
        try:
            from everstaff.knowledge.manager import KnowledgeManager
            return KnowledgeManager(self._spec.knowledge_base)
        except Exception as exc:
            logger.debug("KnowledgeManager unavailable: %s", exc)
            from everstaff.nulls import NullKnowledgeProvider
            return NullKnowledgeProvider()

    def _build_sub_agent_provider(self, model_id: str, workdir: Path, session_id: str, cancellation: "CancellationEvent"):
        if not getattr(self._spec, "sub_agents", None):
            from everstaff.nulls import NullSubAgentProvider
            return NullSubAgentProvider()
        from everstaff.agents.sub_agent_provider import DefaultSubAgentProvider

        specs = []
        for key, sub_spec in self._spec.sub_agents.items():
            if not sub_spec.name:
                sub_spec = sub_spec.model_copy(update={"name": key})
            specs.append(sub_spec)

        return DefaultSubAgentProvider(
            specs=specs,
            env=self._env,
            parent_model_id=model_id,
            parent_session_id=session_id,
            parent_cancellation=cancellation,
            parent_hooks=self._hooks,
        )

    async def _build_mcp_provider(self):
        if not self._spec.mcp_servers:
            from everstaff.nulls import NullMcpProvider
            return NullMcpProvider()
        try:
            from everstaff.mcp_client.provider import DefaultMcpProvider
            provider = DefaultMcpProvider(self._spec.mcp_servers)
            await provider.connect_all()
            return provider
        except Exception as exc:
            logger.warning("MCP provider setup failed, falling back to NullMcpProvider: %s", exc)
            from everstaff.nulls import NullMcpProvider
            return NullMcpProvider()

    def _build_workflow_tool(
        self,
        session_id: str,
        model_id: str,
        cancellation: "CancellationEvent",
        tracer: Any,
        memory: Any = None,
    ):
        if not getattr(self._spec, "workflow", None):
            return None
        from everstaff.workflow.factory import WorkflowSubAgentFactory
        from everstaff.workflow.dag_tool import DAGTool
        factory = WorkflowSubAgentFactory(
            available_agents=self._spec.sub_agents or {},
            env=self._env,
            parent_session_id=session_id,
            parent_cancellation=cancellation,
            parent_model_id=model_id,
        )
        return DAGTool(
            factory=factory,
            max_parallel=self._spec.workflow.max_parallel,
            cancellation=cancellation,
            tracer=tracer,
            session_id=session_id,
            coordinator_name=self._spec.agent_name,
            memory=memory,
        )

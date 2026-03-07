"""API package — factory function to build the FastAPI app."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


def create_app(config=None, *, sessions_dir: str | None = None) -> FastAPI:
    from everstaff.core.config import load_config
    if config is None:
        config = load_config()

    # Allow overriding sessions_dir at app-creation time (useful in tests)
    if sessions_dir is not None:
        config = config.model_copy(update={"sessions_dir": sessions_dir})

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup: start all channels
        cm = app.state.channel_manager
        await cm.start_all()
        logger.info("All channels started (%d registered)", len(cm._channels))

        # Startup: optionally start daemon
        if config.daemon.enabled:
            logger.info("Daemon enabled — initializing AgentDaemon (agents_dir=%s)", config.agents_dir)
            try:
                from everstaff.daemon.agent_daemon import AgentDaemon
                from everstaff.core.factories import build_file_store
                from everstaff.daemon.state_store import DaemonStateStore
                from everstaff.nulls import NullTracer
                from everstaff.llm.litellm_client import LiteLLMClient

                file_store = build_file_store(config.storage, config.sessions_dir)
                daemon_state_store = DaemonStateStore(file_store)

                def _daemon_llm_factory(*, model_kind: str = "fast", **kw):
                    """Create a real LLM client for daemon ThinkEngine."""
                    mapping = config.resolve_model(model_kind)
                    logger.debug("Daemon llm_factory: model_kind=%s → model_id=%s", model_kind, mapping.model_id)
                    return LiteLLMClient(model=mapping.model_id, max_tokens=mapping.max_tokens, temperature=mapping.temperature)

                class _DaemonRuntimeProxy:
                    """Wraps AgentBuilder: build() + run() in a single .run() call.

                    AgentLoop calls ``runtime.run(task_prompt)`` expecting a simple
                    async run method.  This proxy lazily builds the full AgentRuntime
                    on first call so the loop doesn't need to know about builders.
                    """
                    def __init__(self, builder):
                        self._builder = builder

                    async def run(self, prompt: str, **kw) -> str:
                        runtime, _ctx = await self._builder.build()
                        return await runtime.run(prompt)

                def _daemon_runtime_factory(*, agent_spec=None, **kw):
                    """Build a DaemonRuntimeProxy for the daemon Act phase.

                    Called by AgentLoop with session_id (the loop session id).
                    Returns a proxy whose .run(prompt) lazily builds and runs
                    a full AgentRuntime via AgentBuilder.
                    """
                    from everstaff.builder.agent_builder import AgentBuilder
                    from everstaff.builder.environment import DefaultEnvironment

                    session_id = kw.get("session_id", "")
                    trigger = kw.get("trigger")
                    # Use scoped channel_manager from AgentLoop if provided, else fall back to global
                    scoped_cm = kw.get("channel_manager", cm)

                    env = DefaultEnvironment(
                        sessions_dir=config.sessions_dir,
                        session_id=session_id,
                        config=config,
                        channel_manager=scoped_cm,
                        mcp_pool=app.state.mcp_pool,
                    )
                    if agent_spec is None:
                        from everstaff.schema.agent_spec import AgentSpec
                        agent_spec = AgentSpec(agent_name="daemon-task")

                    builder = AgentBuilder(
                        spec=agent_spec,
                        env=env,
                        trigger=trigger,
                    )
                    return _DaemonRuntimeProxy(builder)

                daemon = AgentDaemon(
                    agents_dir=config.agents_dir,
                    daemon_state_store=daemon_state_store,
                    tracer=NullTracer(),
                    llm_factory=_daemon_llm_factory,
                    runtime_factory=_daemon_runtime_factory,
                    channel_manager=cm,
                    channel_registry=channel_registry,
                    sessions_dir=config.sessions_dir,
                    session_index=getattr(app.state, 'session_index', None),
                )
                await daemon.start()
                app.state.daemon = daemon
                logger.info("AgentDaemon started successfully")
            except Exception:
                logger.exception("Failed to start AgentDaemon")
        else:
            logger.info("Daemon disabled — skipping AgentDaemon startup")

        yield

        # Shutdown: destroy all sandbox executors
        executor_mgr = getattr(app.state, "executor_manager", None)
        if executor_mgr is not None:
            await executor_mgr.destroy_all()
            logger.info("All sandbox executors destroyed")

        # Shutdown: stop daemon if running
        daemon = getattr(app.state, "daemon", None)
        if daemon is not None:
            await daemon.stop()
            logger.info("AgentDaemon stopped")

        # Shutdown: close MCP connection pool
        mcp_pool = getattr(app.state, "mcp_pool", None)
        if mcp_pool is not None:
            await mcp_pool.close()
            logger.info("MCP connection pool closed")

        # Shutdown: stop all channels
        await cm.stop_all()
        logger.info("All channels stopped")

    app = FastAPI(title="Agent Framework API", version="0.2.0", lifespan=lifespan)
    app.state.config = config

    # Build and attach MCP connection pool
    from everstaff.mcp_client.pool import McpConnectionPool
    mcp_pool = McpConnectionPool(idle_timeout=300.0)
    mcp_pool.start_cleanup_loop()
    app.state.mcp_pool = mcp_pool

    # Build and attach FileStore to app.state before registering routers
    from everstaff.core.factories import build_file_store, build_channel_manager_from_registry, build_channel_registry
    _sessions_path = sessions_dir or config.sessions_dir
    _file_store = build_file_store(config.storage, _sessions_path)
    app.state.file_store = _file_store

    # Build and attach SessionIndex for fast session lookup
    from everstaff.session.index import SessionIndex as _SessionIndex
    _sessions_resolved = Path(_sessions_path).expanduser().resolve()
    _session_index = _SessionIndex(_sessions_resolved)
    if not _session_index._path.exists() and _sessions_resolved.exists():
        _session_index.rebuild()
    app.state.session_index = _session_index

    # Build and attach ExecutorManager if sandbox is enabled
    if config.sandbox.enabled:
        from everstaff.sandbox.manager import ExecutorManager
        from everstaff.sandbox.process_sandbox import ProcessSandbox
        from everstaff.core.secret_store import SecretStore
        from everstaff.core.factories import build_memory_store as _build_memory_store

        _secret_store = SecretStore.from_environ()
        _sandbox_memory = _build_memory_store(config.storage, _sessions_path)
        _sandbox_memory._index = _session_index
        _sessions_resolved = Path(_sessions_path).expanduser().resolve()

        def _sandbox_factory():
            return ProcessSandbox(sessions_dir=_sessions_resolved)

        _mem0_client = None
        if config.memory.enabled:
            try:
                from everstaff.memory.mem0_client import Mem0Client
                _llm_model_id = config.resolve_model(config.memory.llm_model_kind).model_id
                _embed_model_id = config.resolve_model(config.memory.embedding_model_kind).model_id
                _mem0_client = Mem0Client(config.memory, _llm_model_id, _embed_model_id)
            except Exception as _exc:
                logger.warning("Failed to create Mem0Client for sandbox: %s", _exc)

        _executor_manager = ExecutorManager(
            factory=_sandbox_factory,
            secret_store=_secret_store,
            memory_store=_sandbox_memory,
            file_store=_file_store,
            config_data=config.model_dump(),
            idle_timeout=config.sandbox.idle_timeout,
            mem0_client=_mem0_client,
        )
        app.state.executor_manager = _executor_manager

    # Build shared Mem0Client for memories API
    app.state.mem0_client = None
    if config.memory.enabled:
        try:
            from everstaff.memory.mem0_client import Mem0Client as _MemClient
            _api_llm = config.resolve_model(config.memory.llm_model_kind).model_id
            _api_embed = config.resolve_model(config.memory.embedding_model_kind).model_id
            app.state.mem0_client = _MemClient(config.memory, _api_llm, _api_embed)
        except Exception as _exc:
            logger.warning("Failed to create shared Mem0Client: %s", _exc)

    # Set up ChannelManager with all configured channels.
    # Build the registry first so both the ChannelManager and channel_registry
    # share the same channel instances — channels are started/stopped once and
    # LarkWsChannel post-injection reaches the instances looked up at runtime.
    from everstaff.channels.websocket import WebSocketChannel

    channel_registry = build_channel_registry(config, _file_store)
    channel_manager = build_channel_manager_from_registry(channel_registry, config)
    app.state.channel_registry = channel_registry

    # Extract lark channels for webhook token verification
    from everstaff.channels.lark import LarkChannel as _LarkChannel
    app.state.lark_channels = [
        ch for ch in channel_manager._channels if isinstance(ch, _LarkChannel)
    ]

    # WebSocketChannel broadcasts to all active ws connections.
    # The connections set is populated by ws.py and attached to app.state.ws_connections.
    # Each entry is a (websocket, session_filter) tuple; session_filter may be None.
    # Event types that are too frequent to log individually
    _WS_NOISY_TYPES = frozenset({"text_delta", "thinking_delta"})

    async def _ws_broadcast(event: dict) -> None:
        import asyncio
        import json
        import logging
        broadcast_logger = logging.getLogger("api.ws_broadcast")
        connections = getattr(app.state, "ws_connections", set())
        if not connections:
            return
        event_session_id = event.get("session_id")
        event_type = event.get("type", "?")
        data = json.dumps(event)

        # Count eligible recipients for logging
        eligible = [
            c for c in connections
            if c[1] is None or c[1] == event_session_id
        ]

        if event_type not in _WS_NOISY_TYPES:
            broadcast_logger.debug("[WS] → %-22s  session=%s  recipients=%d",
                          event_type, (event_session_id or "")[:8] or "?", len(eligible))

        async def _send(conn_tuple):
            ws, session_filter = conn_tuple
            if session_filter is not None and event_session_id != session_filter:
                return
            try:
                await ws.send_text(data)
            except Exception as e:
                broadcast_logger.debug("[WS] send failed  session=%s  type=%s  err=%s",
                              (event_session_id or "")[:8] or "?", event_type, e)

        await asyncio.gather(*[_send(c) for c in connections], return_exceptions=True)

    ws_channel = WebSocketChannel(broadcast_fn=_ws_broadcast)
    channel_manager.register(ws_channel)
    app.state.channel_manager = channel_manager
    app.state.ws_connections = set()  # Tracks active WebSocket connections for broadcast

    # Set resolve callback on ChannelManager so any channel resolution
    # automatically persists to session.json and resumes the session.
    async def _on_resolve(hitl_id: str, decision: str, comment=None, grant_scope=None, permission_pattern=None):
        from everstaff.api.hitl import _resolve_hitl_internal
        await _resolve_hitl_internal(app, hitl_id, decision, comment, grant_scope=grant_scope, permission_pattern=permission_pattern)

    channel_manager._on_resolve = _on_resolve

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"], allow_credentials=True,
        allow_methods=["*"], allow_headers=["*"],
    )

    # Auth middleware (if configured)
    auth_config = getattr(config, 'auth', None)
    if auth_config is not None and auth_config.enabled:
        if not auth_config.providers:
            raise ValueError("auth.enabled is true but no providers are configured")
        from everstaff.api.auth.middleware import AuthMiddleware
        from everstaff.api.auth.models import OIDCCodeFlowProviderConfig

        # Mount OIDC Code Flow router and make auth routes public
        oidc_code_configs = [
            p for p in auth_config.providers
            if isinstance(p, OIDCCodeFlowProviderConfig)
        ]
        if oidc_code_configs:
            from everstaff.api.auth.providers.oidc_code import OIDCCodeFlowProvider
            from everstaff.api.auth.router import make_auth_router

            oidc_code_provider = OIDCCodeFlowProvider(oidc_code_configs[0])
            app.include_router(make_auth_router(oidc_code_provider))

            # Add auth routes to public routes so middleware won't block them
            auth_public = ["/auth/login", "/auth/callback", "/auth/logout"]
            existing_public = auth_config.public_routes or []
            auth_config = auth_config.model_copy(
                update={"public_routes": list(existing_public) + auth_public}
            )

        app.add_middleware(AuthMiddleware, auth_config=auth_config)
        app.state.auth_providers = AuthMiddleware._build_providers(auth_config.providers)

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        from everstaff.schema.api_models import ErrorResponse
        return JSONResponse(
            status_code=exc.status_code,
            content=ErrorResponse(error=str(exc.detail)).model_dump(),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        from everstaff.schema.api_models import ErrorResponse
        return JSONResponse(
            status_code=422,
            content=ErrorResponse(
                error="Validation error",
                detail=str(exc.errors()),
            ).model_dump(),
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        from everstaff.schema.api_models import ErrorResponse
        import logging
        logging.getLogger(__name__).error("Unhandled error: %s", exc, exc_info=True)
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(error="Internal server error", detail=str(exc)).model_dump(),
        )

    @app.get("/api/ping")
    async def ping(request: Request):
        user = getattr(request.state, "user", None)
        return {
            "status": "ok",
            "user": user.model_dump() if user else None,
        }

    from everstaff.api.agents import make_router as make_agents_router
    from everstaff.api.sessions import make_router as make_sessions_router
    from everstaff.api.traces import make_router as make_traces_router
    from everstaff.api.ws import make_router as make_ws_router
    from everstaff.api.hitl import make_router as make_hitl_router
    from everstaff.api.skills import make_router as make_skills_router
    from everstaff.api.tools import make_router as make_tools_router
    from everstaff.api.config_api import make_router as make_config_router
    from everstaff.api.stats import make_router as make_stats_router
    from everstaff.api.mcp_api import make_router as make_mcp_router
    from everstaff.api.webhooks import lark_router
    from everstaff.api.daemon import daemon_router
    from everstaff.api.memories import make_router as make_memories_router

    app.include_router(make_agents_router(config), prefix="/api")
    app.include_router(make_sessions_router(config), prefix="/api")
    app.include_router(make_traces_router(config), prefix="/api")
    app.include_router(make_ws_router(config), prefix="/api")
    app.include_router(make_hitl_router(config), prefix="/api")
    app.include_router(make_skills_router(config), prefix="/api")
    app.include_router(make_tools_router(config), prefix="/api")
    app.include_router(make_config_router(config), prefix="/api")
    app.include_router(make_stats_router(config), prefix="/api")
    app.include_router(make_mcp_router(config), prefix="/api")
    app.include_router(lark_router, prefix="/api")
    app.include_router(daemon_router)
    app.include_router(make_memories_router(), prefix="/api")

    # Mount frontend static files (must be LAST — after all API routers)
    if config.web.enabled:
        from everstaff.web_ui import mount_web_ui
        mount_web_ui(app)

    return app

"""AgentDaemon -- top-level orchestrator for autonomous agent loops.

On start, scans ``agents_dir`` for YAML files whose ``autonomy.enabled``
flag is *True*.  For each autonomous agent it wires up:

* An EventBus subscription
* SchedulerSensor instances (for cron/interval triggers)
* A ThinkEngine (for LLM-based decision making)
* An AgentLoop (the wake -> think -> act -> reflect cycle)

All sensors and loops are managed through SensorManager and LoopManager
respectively.  The daemon supports **hot reload**: calling ``reload()``
re-scans the agents directory and starts/stops loops to match the current
set of enabled autonomous agents.

The daemon also watches ``agents_dir`` for file changes using ``watchfiles``
and automatically triggers a debounced reload when ``.yaml`` files are
created, modified, or deleted.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from everstaff.protocols import TracingBackend

logger = logging.getLogger(__name__)


class AgentDaemon:
    """Top-level orchestrator that discovers and manages autonomous agents.

    Parameters
    ----------
    agents_dir:
        Filesystem directory containing agent YAML definitions.
    daemon_state_store:
        ``DaemonStateStore`` instance for persisting daemon state.
    tracer:
        Object satisfying the ``TracingBackend`` protocol.
    llm_factory:
        Callable that returns an LLM client.  Called with keyword arguments
        including ``model_kind``.
    runtime_factory:
        Callable that returns a runtime for executing agent tasks.  Called
        with keyword arguments including ``session_id`` and
        ``parent_session_id``.
    channel_manager:
        Optional channel manager for HITL communication.
    """

    def __init__(
        self,
        agents_dir: str | Path,
        daemon_state_store: Any,
        tracer: "TracingBackend",
        llm_factory: Callable[..., Any],
        runtime_factory: Callable[..., Any],
        mem0_client: Any = None,
        channel_manager: Any = None,
        channel_registry: dict[str, Any] | None = None,
        sessions_dir: str | Path | None = None,
        session_index: Any = None,
        app: Any = None,
        lark_connections: dict | None = None,
    ) -> None:
        self._agents_dir = Path(agents_dir)
        self._state_store = daemon_state_store
        self._mem0 = mem0_client
        self._tracer = tracer
        self._llm_factory = llm_factory
        self._runtime_factory = runtime_factory
        self._channel_manager = channel_manager
        self._channel_registry = channel_registry or {}
        self._sessions_dir = sessions_dir
        self._session_index = session_index
        self._app = app
        self._lark_connections = lark_connections or {}
        self._running = False
        self._watcher_task: asyncio.Task | None = None
        self._reload_debounce: float = 1.0  # seconds

        from everstaff.daemon.event_bus import EventBus
        from everstaff.daemon.sensor_manager import SensorManager
        from everstaff.daemon.loop_manager import LoopManager

        self._event_bus = EventBus()
        self._sensor_manager = SensorManager(self._event_bus)
        self._loop_manager = LoopManager()

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def event_bus(self) -> Any:
        """The shared EventBus instance."""
        return self._event_bus

    @property
    def sensor_manager(self) -> Any:
        """The SensorManager instance."""
        return self._sensor_manager

    @property
    def loop_manager(self) -> Any:
        """The LoopManager instance."""
        return self._loop_manager

    @property
    def is_running(self) -> bool:
        """Whether the daemon is currently running."""
        return self._running

    # ------------------------------------------------------------------
    # Agent discovery
    # ------------------------------------------------------------------

    def _discover_autonomous_agents(self) -> dict[str, Any]:
        """Scan agents_dir (and builtin_agents) for autonomous agents.

        Only agents whose ``autonomy.enabled`` is True are included.
        Builtin agents are scanned first; user agents override by name.
        """
        from everstaff.utils.yaml_loader import load_yaml
        from everstaff.schema.agent_spec import AgentSpec
        from everstaff.core.config import _builtin_agents_path

        result: dict[str, Any] = {}

        scan_dirs = []
        builtin_p = _builtin_agents_path()
        if builtin_p:
            scan_dirs.append(Path(builtin_p))
        scan_dirs.append(self._agents_dir)

        for scan_dir in scan_dirs:
            if not scan_dir.exists():
                if scan_dir == self._agents_dir:
                    logger.warning("agents_dir does not exist: %s", scan_dir)
                continue
            logger.debug("Scanning agents dir=%s", scan_dir)
            for yaml_file in sorted(scan_dir.glob("*.yaml")):
                try:
                    yaml_data = load_yaml(yaml_file)
                    agent_name = yaml_data.pop("name", None) or yaml_data.pop("agent_name", None) or yaml_file.stem
                    spec = AgentSpec(agent_name=agent_name, **yaml_data)
                    if spec.autonomy.enabled:
                        result[spec.agent_name] = spec
                        logger.debug("Discovered autonomous agent: %s (triggers=%d)",
                                     spec.agent_name, len(spec.autonomy.triggers))
                except Exception as exc:
                    logger.warning("Failed to load agent '%s': %s", yaml_file.name, exc)

        logger.info("Discovery complete: %d autonomous agent(s) found: %s",
                     len(result), list(result.keys()))
        return result

    # ------------------------------------------------------------------
    # Per-agent lifecycle
    # ------------------------------------------------------------------

    async def _start_agent(self, name: str, spec: Any) -> None:
        """Wire up and start all components for a single autonomous agent."""
        from everstaff.daemon.think_engine import ThinkEngine
        from everstaff.daemon.sensors.scheduler import SchedulerSensor
        from everstaff.daemon.agent_loop import AgentLoop

        logger.info("starting agent=%s think_model=%s act_model=%s",
                     name, spec.autonomy.think_model, spec.autonomy.act_model)

        # Subscribe to EventBus
        self._event_bus.subscribe(name)

        # Register chat_id → agent routes on LarkWsConnections
        for ref in spec.hitl_channels:
            channel = self._channel_registry.get(ref.ref)
            if channel is None:
                continue
            overrides = ref.overrides()
            chat_id = overrides.get("chat_id") or getattr(channel, "_chat_id", "")
            if chat_id:
                app_id = getattr(channel, "_app_id", "")
                conn = self._lark_connections.get(app_id)
                if conn:
                    conn.register_chat_route(chat_id, name)

        # Create and register sensors for this agent's triggers
        cron_triggers = [
            t for t in spec.autonomy.triggers
            if t.type in ("cron", "interval")
        ]
        if cron_triggers:
            logger.info("registering cron/interval triggers agent=%s count=%d", name, len(cron_triggers))
            sensor = SchedulerSensor(triggers=cron_triggers, agent_name=name)
            self._sensor_manager.register(sensor, agent_name=name)
            await sensor.start(self._event_bus)

        # WebhookSensor for webhook triggers
        webhook_triggers = [t for t in spec.autonomy.triggers if t.type == "webhook"]
        if webhook_triggers and self._app and spec.uuid:
            from everstaff.daemon.sensors.webhook import WebhookSensor
            ws = WebhookSensor(triggers=webhook_triggers, agent_name=name, agent_uuid=spec.uuid, app=self._app)
            self._sensor_manager.register(ws, agent_name=name)
            await ws.start(self._event_bus)

        # FileWatchSensor for file_watch triggers
        file_watch_triggers = [t for t in spec.autonomy.triggers if t.type == "file_watch"]
        if file_watch_triggers:
            from everstaff.daemon.sensors.file_watch import FileWatchSensor
            fws = FileWatchSensor(triggers=file_watch_triggers, agent_name=name)
            self._sensor_manager.register(fws, agent_name=name)
            await fws.start(self._event_bus)

        # InternalSensor for internal triggers
        internal_triggers = [t for t in spec.autonomy.triggers if t.type == "internal"]
        internal_sensor = None
        if internal_triggers:
            from everstaff.daemon.sensors.internal import InternalSensor
            internal_sensor = InternalSensor(triggers=internal_triggers, agent_name=name)
            self._sensor_manager.register(internal_sensor, agent_name=name)
            await internal_sensor.start(self._event_bus)

        # Create ThinkEngine
        think_llm = self._llm_factory(model_kind=spec.autonomy.think_model)
        think_engine = ThinkEngine(
            llm_client=think_llm,
            tracer=self._tracer,
            daemon_state_store=self._state_store,
            agent_uuid=spec.uuid,
            mem0_client=self._mem0,
        )

        # Create per-agent runtime factory (closure captures agent spec)
        base_factory = self._runtime_factory

        def agent_runtime_factory(**kw):
            return base_factory(agent_spec=spec, **kw)

        # Create AgentLoop
        loop = AgentLoop(
            agent_name=name,
            event_bus=self._event_bus,
            think_engine=think_engine,
            runtime_factory=agent_runtime_factory,
            daemon_state_store=self._state_store,
            agent_uuid=spec.uuid,
            tracer=self._tracer,
            mem0_client=self._mem0,
            goals=spec.autonomy.goals,
            tick_interval=spec.autonomy.tick_interval,
            channel_manager=self._channel_manager,
            sessions_dir=self._sessions_dir,
            triggers=spec.autonomy.triggers,
            hitl_channels=spec.hitl_channels,
            channel_registry=self._channel_registry,
            session_index=self._session_index,
            internal_sensor=internal_sensor,
        )

        await self._loop_manager.start(loop)

    async def _stop_agent(self, name: str) -> None:
        """Stop all components for a single agent."""
        logger.info("stopping agent=%s", name)
        await self._loop_manager.stop(name)
        await self._sensor_manager.unregister_for(name)
        self._event_bus.unsubscribe(name)
        logger.info("agent stopped agent=%s", name)

    # ------------------------------------------------------------------
    # Daemon lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Discover and start all autonomous agents."""
        logger.info("daemon starting")
        logger.info("agents_dir=%s", self._agents_dir)
        self._running = True

        # Inject EventBus into LarkWs connections
        for conn in self._lark_connections.values():
            conn._event_bus = self._event_bus

        agents = self._discover_autonomous_agents()
        for name, spec in agents.items():
            try:
                await self._start_agent(name, spec)
                logger.info("agent started agent=%s", name)
            except Exception as exc:
                logger.error("failed to start agent=%s error=%s", name, exc)
        # Start watching agents_dir for file changes
        self._watcher_task = asyncio.create_task(
            self._watch_agents_dir(), name="daemon-agents-watcher",
        )
        logger.info("daemon ready agents=%d", len(agents))

    async def stop(self) -> None:
        """Stop all running agents and sensors."""
        logger.info("daemon shutting down")
        if self._watcher_task and not self._watcher_task.done():
            self._watcher_task.cancel()
            try:
                await self._watcher_task
            except asyncio.CancelledError:
                pass
            self._watcher_task = None
        await self._loop_manager.stop_all()
        await self._sensor_manager.stop_all()
        self._running = False
        logger.info("daemon stopped")

    async def _watch_agents_dir(self) -> None:
        """Watch agents_dir for .yaml changes and trigger debounced reload."""
        try:
            from watchfiles import awatch, Change
        except ImportError:
            logger.warning("watchfiles not installed, agents_dir auto-reload disabled")
            return

        logger.info("watching agents_dir=%s for changes", self._agents_dir)
        try:
            async for changes in awatch(self._agents_dir):
                # Only react to .yaml file changes
                yaml_changes = [
                    (ct, p) for ct, p in changes if p.endswith(".yaml")
                ]
                if not yaml_changes:
                    continue
                for ct, p in yaml_changes:
                    label = {Change.added: "added", Change.modified: "modified", Change.deleted: "deleted"}.get(ct, "unknown")
                    logger.info("agents_dir change: %s %s", label, Path(p).name)
                # Debounce: wait a bit in case multiple files change at once
                await asyncio.sleep(self._reload_debounce)
                try:
                    await self.reload()
                except Exception as exc:
                    logger.error("auto-reload after file change failed: %s", exc, exc_info=True)
        except asyncio.CancelledError:
            logger.info("agents_dir watcher stopped")
        except Exception as exc:
            logger.error("agents_dir watcher crashed: %s", exc, exc_info=True)

    async def reload(self) -> None:
        """Hot reload: re-scan agents directory and reconcile running loops.

        * Agents whose YAML was removed or whose ``autonomy.enabled`` became
          False are stopped.
        * Newly added autonomous agents are started.
        * Existing agents are restarted to pick up any config changes
          (permissions, instructions, tools, etc.).
        """
        logger.info("hot reload triggered")
        current_agents = self._discover_autonomous_agents()
        current_names = set(current_agents.keys())
        running_names = set(self._loop_manager._loops.keys())

        to_stop = running_names - current_names
        to_start = current_names - running_names
        to_restart = running_names & current_names
        logger.info("Reload: to_stop=%s, to_start=%s, to_restart=%s",
                     list(to_stop), list(to_start), list(to_restart))

        # Stop agents no longer present or no longer autonomous
        for name in to_stop:
            await self._stop_agent(name)

        # Restart existing agents with fresh specs from YAML
        for name in to_restart:
            try:
                await self._stop_agent(name)
                await self._start_agent(name, current_agents[name])
            except Exception as exc:
                logger.error("Failed to restart agent '%s' during reload: %s", name, exc)

        # Start newly discovered agents
        for name in to_start:
            try:
                await self._start_agent(name, current_agents[name])
            except Exception as exc:
                logger.error("Failed to start agent '%s' during reload: %s", name, exc)
        logger.info("hot reload complete")

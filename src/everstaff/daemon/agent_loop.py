"""AgentLoop -- core lifecycle: wake -> think -> act -> reflect."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from everstaff.daemon.event_bus import EventBus
    from everstaff.daemon.think_engine import ThinkEngine
    from everstaff.protocols import AgentEvent, Decision, TracingBackend

logger = logging.getLogger(__name__)


def _apply_channel_overrides(channel: Any, overrides: dict) -> Any:
    """Return a shallow copy of channel with overrides applied.

    Channel attributes use underscore prefix internally (e.g., chat_id → _chat_id).
    """
    import copy
    cloned = copy.copy(channel)
    for field, value in overrides.items():
        attr = f"_{field}"
        if hasattr(cloned, attr):
            setattr(cloned, attr, value)
        else:
            logger.debug(
                "_apply_channel_overrides: channel has no attribute '%s', skipping override '%s'",
                attr, field,
            )
    return cloned


class AgentLoop:
    """Runs the autonomous agent lifecycle: wake -> think -> act -> reflect.

    Each cycle:
    1. **Wake** -- wait for an event from the EventBus.
    2. **Think** -- call the ThinkEngine to decide what to do.
    3. **Act** -- if the decision is ``execute``, run the runtime.
    4. **Reflect** -- record the episode and update working memory.

    The loop creates a parent session per cycle.  Think and act are child
    sessions under that parent, enabling hierarchical tracing.
    """

    def __init__(
        self,
        agent_name: str,
        event_bus: "EventBus",
        think_engine: "ThinkEngine",
        runtime_factory: Any,
        daemon_state_store: Any,
        agent_uuid: str,
        tracer: "TracingBackend",
        mem0_client: Any = None,
        goals: list[Any] | None = None,
        tick_interval: float = 60.0,
        channel_manager: Any = None,
        sessions_dir: str | Path | None = None,
        triggers: list[Any] | None = None,           # list[TriggerConfig]
        agent_hitl_channels: list[Any] | None = None, # list[HitlChannelRef]
        channel_registry: dict[str, Any] | None = None, # dict[name → HitlChannel]
        session_index: Any = None,
        internal_sensor: Any = None,
    ) -> None:
        self._agent_name = agent_name
        self._bus = event_bus
        self._think = think_engine
        self._runtime_factory = runtime_factory
        self._state_store = daemon_state_store
        self._agent_uuid = agent_uuid
        self._tracer = tracer
        self._mem0 = mem0_client

        self._goals = goals or []
        self._tick_interval = tick_interval
        self._channel_manager = channel_manager
        self._running = False
        self._busy = False  # overlap detection
        self._sessions_dir: Path | None = Path(sessions_dir) if sessions_dir else None
        self._triggers = triggers or []
        self._agent_hitl_channels = agent_hitl_channels or []
        self._channel_registry = channel_registry or {}
        self._session_index = session_index
        self._internal_sensor = internal_sensor

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def agent_name(self) -> str:
        return self._agent_name

    @property
    def is_running(self) -> bool:
        return self._running

    # ------------------------------------------------------------------
    # Channel resolution
    # ------------------------------------------------------------------

    def _resolve_channels(self, event: Any) -> Any:
        """Return a scoped ChannelManager for this trigger event.

        Priority:
        1. trigger.hitl_channels (if trigger found and explicitly set)
        2. agent-level hitl_channels (if non-empty)
        3. self._channel_manager (global fallback)
        """
        from everstaff.channels.manager import ChannelManager

        # Extract trigger_id: "cron.daily-digest" → "daily-digest"
        event_type = getattr(event, "type", "") or ""
        trigger_id = event_type.split(".", 1)[-1] if "." in event_type else event_type

        # Find matching trigger by id
        trigger = next((t for t in self._triggers if t.id == trigger_id), None)

        # Determine which refs to use
        refs = None
        if trigger is not None and trigger.hitl_channels is not None:
            refs = trigger.hitl_channels
        elif self._agent_hitl_channels:
            refs = self._agent_hitl_channels

        if refs is None:
            return self._channel_manager  # fallback to global

        # Build scoped ChannelManager from refs + registry
        scoped = ChannelManager()
        for ref in refs:
            channel = self._channel_registry.get(ref.ref)
            if channel is None:
                logger.warning(
                    "[Loop:%s] Channel ref '%s' not found in registry, skipping",
                    self._agent_name, ref.ref,
                )
                continue
            overrides = ref.overrides()
            if overrides:
                channel = _apply_channel_overrides(channel, overrides)
            scoped.register(channel)
        return scoped

    # ------------------------------------------------------------------
    # Single cycle
    # ------------------------------------------------------------------

    async def run_once(self) -> None:
        """Execute a single wake -> think -> act -> reflect cycle."""
        from everstaff.protocols import TraceEvent

        # 1. Wake -- try to get an event
        event = await self._bus.wait_for(self._agent_name, timeout=self._tick_interval)
        if event is None:
            logger.debug("[Loop:%s] Tick — no event (timeout=%.0fs)", self._agent_name, self._tick_interval)
            return  # No event, nothing to do

        # Create a parent session id for this cycle
        loop_session_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()
        self._write_loop_session(loop_session_id, event, now)
        logger.info("[Loop:%s] ▶ Cycle start — trigger=%s:%s, session=%s",
                     self._agent_name, event.source, event.type, loop_session_id[:8])

        # Trace: wake
        self._tracer.on_event(TraceEvent(
            kind="loop_wake",
            session_id=loop_session_id,
            data={"agent": self._agent_name, "trigger_type": event.type, "trigger_source": event.source},
        ))

        # 2. Think -- decide what to do
        self._tracer.on_event(TraceEvent(
            kind="loop_think_start",
            session_id=loop_session_id,
            data={"agent": self._agent_name},
        ))

        pending = self._bus.drain(self._agent_name)
        logger.debug("[Loop:%s] Think — pending_events=%d", self._agent_name, len(pending))
        decision = await self._think.think(
            agent_name=self._agent_name,
            trigger=event,
            pending_events=pending,
            autonomy_goals=self._goals,
            parent_session_id=loop_session_id,
        )

        logger.info("[Loop:%s] Think → decision=%s, task='%s', reasoning='%s'",
                     self._agent_name, decision.action, decision.task_prompt[:80] if decision.task_prompt else '-',
                     decision.reasoning[:80] if decision.reasoning else '-')

        self._tracer.on_event(TraceEvent(
            kind="loop_think_end",
            session_id=loop_session_id,
            data={"agent": self._agent_name, "decision": decision.action, "task": decision.task_prompt},
        ))

        # 3. Act (only if decision is "execute")
        result = ""
        start_time = time.monotonic()
        if decision.action == "execute" and decision.task_prompt:
            logger.info("[Loop:%s] Act — executing task: '%s'", self._agent_name, decision.task_prompt[:100])
            self._tracer.on_event(TraceEvent(
                kind="loop_act_start",
                session_id=loop_session_id,
                data={"agent": self._agent_name, "task": decision.task_prompt},
            ))

            scoped_cm = self._resolve_channels(event)
            runtime = self._runtime_factory(
                session_id=str(uuid4()),
                parent_session_id=loop_session_id,
                trigger=event,
                channel_manager=scoped_cm,
            )
            try:
                result = await runtime.run(decision.task_prompt)
                logger.info("[Loop:%s] Act — completed (result_len=%d)", self._agent_name, len(str(result)))
            except Exception as exc:
                logger.error("[Loop:%s] Act — FAILED: %s", self._agent_name, exc)
                result = f"ERROR: {exc}"

            duration_ms = int((time.monotonic() - start_time) * 1000)

            self._tracer.on_event(TraceEvent(
                kind="loop_act_end",
                session_id=loop_session_id,
                data={"agent": self._agent_name, "result_preview": str(result)[:200]},
                duration_ms=float(duration_ms),
            ))
        else:
            logger.info("[Loop:%s] Skip — reason: %s", self._agent_name, decision.reasoning[:100] if decision.reasoning else 'no reason')
            duration_ms = int((time.monotonic() - start_time) * 1000)

        # 4. Reflect
        if decision.action == "execute":
            # Store episode in mem0 (semantic, searchable)
            if self._mem0:
                episode_summary = (
                    f"[{datetime.now(timezone.utc).isoformat()}] "
                    f"Trigger: {event.source}:{event.type} | "
                    f"Action: {decision.task_prompt} | "
                    f"Result: {str(result)[:500]} | "
                    f"Duration: {duration_ms}ms"
                )
                await self._mem0.add(
                    [{"role": "assistant", "content": episode_summary}],
                    agent_id=self._agent_name,
                    run_id=loop_session_id,
                )
            if self._internal_sensor is not None:
                self._internal_sensor.notify_episode()

        # Update structured state with the decision
        state = await self._state_store.load(self._agent_uuid)
        state.recent_decisions.append({
            "action": decision.action,
            "task": decision.task_prompt,
            "reasoning": decision.reasoning,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        state.recent_decisions = state.recent_decisions[-20:]
        await self._state_store.save(self._agent_uuid, state)

        # Trace: reflect
        self._tracer.on_event(TraceEvent(
            kind="loop_reflect",
            session_id=loop_session_id,
            data={"agent": self._agent_name, "decision": decision.action},
        ))
        self._finish_loop_session(loop_session_id, decision, duration_ms, result)
        logger.info("[Loop:%s] ■ Cycle end — decision=%s, duration=%dms, session=%s",
                     self._agent_name, decision.action, duration_ms, loop_session_id[:8])

    # ------------------------------------------------------------------
    # Continuous loop
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Run the loop continuously until stopped or cancelled."""
        logger.info("[Loop:%s] Loop started — tick_interval=%.0fs",
                     self._agent_name, self._tick_interval)
        self._running = True
        cycle_count = 0
        try:
            while self._running:
                try:
                    cycle_count += 1
                    await self.run_once()
                except asyncio.CancelledError:
                    logger.info("[Loop:%s] Loop cancelled after %d cycle(s)", self._agent_name, cycle_count)
                    break
                except Exception as exc:
                    logger.error("[Loop:%s] Cycle error (cycle #%d): %s", self._agent_name, cycle_count, exc)
                    await asyncio.sleep(1)  # brief backoff on error
        finally:
            self._running = False
            logger.info("[Loop:%s] Loop exited — total cycles: %d", self._agent_name, cycle_count)

    # ------------------------------------------------------------------
    # Loop session persistence
    # ------------------------------------------------------------------

    def _write_loop_session(self, session_id: str, event: Any, now: str) -> None:
        """Write a stub session.json for this loop cycle to sessions_dir."""
        if self._sessions_dir is None:
            return
        session_dir = self._sessions_dir / session_id
        try:
            session_dir.mkdir(parents=True, exist_ok=True)
            payload_str = str(event.payload) if event.payload else ""
            trigger_msg = f"Triggered by {event.source}:{event.type}"
            if payload_str:
                trigger_msg += f"\nPayload: {payload_str}"
            data = {
                "session_id": session_id,
                "agent_name": self._agent_name,
                "status": "running",
                "created_at": now,
                "updated_at": now,
                "parent_session_id": None,
                "metadata": {
                    "title": f"Daemon: {event.source}:{event.type}",
                },
                "messages": [{"role": "user", "content": trigger_msg}],
                "hitl_requests": [],
            }
            (session_dir / "session.json").write_text(json.dumps(data, indent=2))
            if self._session_index is not None:
                from everstaff.session.index import IndexEntry
                self._session_index.upsert(IndexEntry(
                    id=session_id, root=session_id, parent=None,
                    agent=self._agent_name, agent_uuid=None,
                    status="running", created_at=now, updated_at=now,
                ))
        except Exception as exc:
            logger.warning("[Loop:%s] Failed to write loop session %s: %s", self._agent_name, session_id, exc)

    def _finish_loop_session(self, session_id: str, decision: Any, duration_ms: int, result: str = "") -> None:
        """Append a completion message and mark the loop session as completed."""
        if self._sessions_dir is None:
            return
        meta_path = self._sessions_dir / session_id / "session.json"
        if not meta_path.exists():
            return
        try:
            data = json.loads(meta_path.read_text())
            if decision.action == "execute":
                content = f"Decision: execute\nTask: {decision.task_prompt}"
                if result:
                    content += f"\nResult: {str(result)[:500]}"
                content += f"\nDuration: {duration_ms}ms"
            elif decision.action == "skip":
                content = f"Decision: skip\nReason: {decision.reasoning}"
            else:
                content = f"Decision: {decision.action}\nReason: {decision.reasoning}"
            data["messages"].append({"role": "assistant", "content": content})
            data["status"] = "completed"
            data["updated_at"] = datetime.now(timezone.utc).isoformat()
            meta_path.write_text(json.dumps(data, indent=2))
            if self._session_index is not None:
                from everstaff.session.index import IndexEntry
                self._session_index.upsert(IndexEntry(
                    id=session_id, root=session_id, parent=None,
                    agent=self._agent_name, agent_uuid=None,
                    status="completed",
                    created_at=data.get("created_at", ""),
                    updated_at=data["updated_at"],
                ))
        except Exception as exc:
            logger.warning("[Loop:%s] Failed to finish loop session %s: %s", self._agent_name, session_id, exc)

    def stop(self) -> None:
        """Signal the loop to stop after the current cycle completes."""
        logger.info("[Loop:%s] Stop requested", self._agent_name)
        self._running = False

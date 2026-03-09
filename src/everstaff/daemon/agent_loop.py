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

    Each cycle produces a single unified session file containing think
    messages, execution results, and completion summary.
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
        hitl_channels: list[Any] | None = None,  # list[HitlChannelRef]
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
        self._hitl_channels = hitl_channels or []
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
        """Return a scoped ChannelManager for this event.

        Uses agent-level hitl_channels if configured, otherwise
        falls back to the default channel_manager.
        """
        from everstaff.channels.manager import ChannelManager

        if not self._hitl_channels:
            return self._channel_manager  # fallback to global

        # Build scoped ChannelManager from refs + registry
        scoped = ChannelManager()
        for ref in self._hitl_channels:
            channel = self._channel_registry.get(ref.ref)
            if channel is None:
                logger.warning(
                    "channel ref not found in registry agent=%s ref=%s",
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
            logger.debug("tick no event agent=%s timeout=%.0fs", self._agent_name, self._tick_interval)
            return  # No event, nothing to do

        # Create a parent session id for this cycle
        loop_session_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()
        self._write_loop_session(loop_session_id, event, now)
        logger.info("cycle start agent=%s trigger=%s:%s session=%s",
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
        logger.debug("think agent=%s pending_events=%d", self._agent_name, len(pending))
        decision, think_messages = await self._think.think(
            agent_name=self._agent_name,
            trigger=event,
            pending_events=pending,
            autonomy_goals=self._goals,
        )

        logger.info("think complete agent=%s decision=%s task=%s reasoning=%s",
                     self._agent_name, decision.action, decision.task_prompt[:80] if decision.task_prompt else '-',
                     decision.reasoning[:80] if decision.reasoning else '-')

        self._append_think_messages(loop_session_id, think_messages)

        self._tracer.on_event(TraceEvent(
            kind="loop_think_end",
            session_id=loop_session_id,
            data={"agent": self._agent_name, "decision": decision.action, "task": decision.task_prompt},
        ))

        # 3. Act (only if decision is "execute")
        result = ""
        start_time = time.monotonic()
        if decision.action == "execute" and decision.task_prompt:
            logger.info("act executing agent=%s task=%s", self._agent_name, decision.task_prompt[:100])
            self._tracer.on_event(TraceEvent(
                kind="loop_act_start",
                session_id=loop_session_id,
                data={"agent": self._agent_name, "task": decision.task_prompt},
            ))

            scoped_cm = self._resolve_channels(event)
            runtime = self._runtime_factory(
                session_id=loop_session_id,
                trigger=event,
                channel_manager=scoped_cm,
            )
            try:
                result = await runtime.run(decision.task_prompt)
                logger.info("act completed agent=%s result_len=%d", self._agent_name, len(str(result)))
            except Exception as exc:
                from everstaff.protocols import HumanApprovalRequired
                if isinstance(exc, HumanApprovalRequired):
                    # HITL pause — session already saved as waiting_for_human.
                    # Broadcast HITL requests to channels (Lark, etc.) so humans
                    # can resolve them. The _on_resolve → _resume_session_task
                    # flow handles resolution and auto-resume.
                    logger.info("act paused for HITL agent=%s session=%s requests=%d already_routed=%s",
                                self._agent_name, loop_session_id[:8], len(exc.requests),
                                getattr(exc, "already_routed", False))
                    # Only broadcast here if the inner runtime didn't already
                    # route via hitl_router (e.g. sandbox path where the
                    # subprocess has no channel_manager).
                    if scoped_cm is not None and not getattr(exc, "already_routed", False):
                        for req in exc.requests:
                            try:
                                await scoped_cm.broadcast(loop_session_id, req)
                            except Exception as bc_err:
                                logger.warning("HITL broadcast failed hitl_id=%s err=%s",
                                               req.hitl_id, bc_err)
                    result = f"Paused: waiting for human approval ({len(exc.requests)} request(s))"
                else:
                    logger.error("act failed agent=%s error=%s", self._agent_name, exc)
                    result = f"ERROR: {exc}"

            duration_ms = int((time.monotonic() - start_time) * 1000)

            self._tracer.on_event(TraceEvent(
                kind="loop_act_end",
                session_id=loop_session_id,
                data={"agent": self._agent_name, "result_preview": str(result)[:200]},
                duration_ms=float(duration_ms),
            ))
        else:
            logger.info("skip agent=%s reason=%s", self._agent_name, decision.reasoning[:100] if decision.reasoning else 'no reason')
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
        logger.info("cycle end agent=%s decision=%s duration=%dms session=%s",
                     self._agent_name, decision.action, duration_ms, loop_session_id[:8])

    # ------------------------------------------------------------------
    # Continuous loop
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Run the loop continuously until stopped or cancelled."""
        logger.info("loop started agent=%s tick_interval=%.0fs",
                     self._agent_name, self._tick_interval)
        self._running = True
        cycle_count = 0
        try:
            while self._running:
                try:
                    cycle_count += 1
                    logger.info("loop cycle agent=%s cycle=%d", self._agent_name, cycle_count)
                    await self.run_once()
                except asyncio.CancelledError:
                    logger.info("loop cancelled agent=%s cycles=%d", self._agent_name, cycle_count)
                    break
                except Exception as exc:
                    logger.error("cycle error agent=%s cycle=%d error=%s", self._agent_name, cycle_count, exc)
                    await asyncio.sleep(1)  # brief backoff on error
        finally:
            self._running = False
            logger.info("loop exited agent=%s total_cycles=%d", self._agent_name, cycle_count)

    # ------------------------------------------------------------------
    # Loop session persistence
    # ------------------------------------------------------------------

    @staticmethod
    def _derive_title(event: Any) -> str:
        """Derive a readable session title from the event."""
        payload = getattr(event, "payload", {}) or {}
        # Try common payload fields for a human-readable snippet
        text = payload.get("content") or payload.get("task") or ""
        if isinstance(text, str) and text.strip():
            snippet = text.strip().replace("\n", " ")
            if len(snippet) > 60:
                snippet = snippet[:57] + "..."
            return snippet
        source = getattr(event, "source", "")
        etype = getattr(event, "type", "")
        return f"Daemon: {source}:{etype}"

    def _write_loop_session(self, session_id: str, event: Any, now: str) -> None:
        """Write a stub session.json for this loop cycle to sessions_dir."""
        if self._sessions_dir is None:
            return
        session_dir = self._sessions_dir / session_id
        try:
            session_dir.mkdir(parents=True, exist_ok=True)
            data = {
                "session_id": session_id,
                "agent_name": self._agent_name,
                "status": "running",
                "created_at": now,
                "updated_at": now,
                "parent_session_id": None,
                "metadata": {
                    "title": self._derive_title(event),
                },
                "messages": [],
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
            logger.warning("failed to write loop session agent=%s session=%s error=%s", self._agent_name, session_id, exc)

    def _append_think_messages(self, session_id: str, think_messages: list) -> None:
        """Append think-phase messages to a separate field in the loop session file.

        Think messages are internal (trigger details, LLM reasoning) and stored
        under ``think_messages`` so they don't pollute the main ``messages``
        array that the runtime uses as conversation history.
        """
        if self._sessions_dir is None:
            return
        meta_path = self._sessions_dir / session_id / "session.json"
        if not meta_path.exists():
            logger.debug("session file not found for appending think messages agent=%s session=%s",
                         self._agent_name, session_id)
            return
        try:
            data = json.loads(meta_path.read_text())
            think_list = data.setdefault("think_messages", [])
            for msg in think_messages:
                think_list.append(msg.to_dict() if hasattr(msg, 'to_dict') else msg)
            data["updated_at"] = datetime.now(timezone.utc).isoformat()
            meta_path.write_text(json.dumps(data, indent=2))
        except Exception as exc:
            logger.warning("failed to append think messages agent=%s session=%s error=%s",
                           self._agent_name, session_id, exc)

    def _finish_loop_session(self, session_id: str, decision: Any, duration_ms: int, result: str = "") -> None:
        """Append a completion message and mark the loop session as completed."""
        if self._sessions_dir is None:
            return
        meta_path = self._sessions_dir / session_id / "session.json"
        if not meta_path.exists():
            return
        try:
            data = json.loads(meta_path.read_text())

            # Don't overwrite status if runtime already set it (e.g. waiting_for_human)
            current_status = data.get("status", "")
            if current_status == "waiting_for_human":
                return

            if decision.action == "execute":
                # Runtime already saved the assistant message with real LLM thinking.
                # Only update status — do NOT append a duplicate assistant message.
                pass
            else:
                thinking = f"Decision: {decision.action}\nReason: {decision.reasoning}"
                content = f"Decide to {decision.action} the loop"
                data.setdefault("think_messages", []).append({"role": "assistant", "content": content, "thinking": thinking, "created_at": datetime.now(timezone.utc).isoformat()})
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
            logger.warning("failed to finish loop session agent=%s session=%s error=%s", self._agent_name, session_id, exc)

    def stop(self) -> None:
        """Signal the loop to stop after the current cycle completes."""
        logger.info("stop requested agent=%s", self._agent_name)
        self._running = False

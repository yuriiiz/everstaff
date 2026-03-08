import asyncio
import pytest
from dataclasses import dataclass
from everstaff.daemon.agent_loop import AgentLoop
from everstaff.daemon.event_bus import EventBus
from everstaff.daemon.think_engine import ThinkEngine
from everstaff.protocols import AgentEvent, Decision, LLMResponse, Message, ToolCallRequest
from everstaff.nulls import NullTracer
from everstaff.daemon.state_store import DaemonState, DaemonStateStore


class InMemoryFileStore:
    def __init__(self):
        self._data: dict[str, bytes] = {}
    async def read(self, path: str) -> bytes:
        if path not in self._data:
            raise FileNotFoundError(path)
        return self._data[path]
    async def write(self, path: str, data: bytes) -> None:
        self._data[path] = data
    async def exists(self, path: str) -> bool:
        return path in self._data
    async def delete(self, path: str) -> None:
        self._data.pop(path, None)
    async def list(self, prefix: str) -> list[str]:
        return [k for k in self._data if k.startswith(prefix)]


class FakeMem0:
    def __init__(self):
        self.added: list[tuple] = []
    async def add(self, messages, **scope):
        self.added.append((messages, scope))
        return []
    async def search(self, query, *, top_k=None, **scope):
        return []


class MockThinkEngine:
    """Returns a fixed decision."""
    def __init__(self, decision: Decision):
        self.decision = decision
        self.called = False

    async def think(self, agent_name, trigger, pending_events, autonomy_goals):
        self.called = True
        return (self.decision, [Message(role="user", content="trigger", created_at="")])


class MockRuntime:
    """Simulates running an agent task."""
    def __init__(self, result: str = "task completed"):
        self.result = result
        self.called = False
        self.last_prompt = ""

    async def run(self, prompt: str, session_id: str = "", parent_session_id: str = ""):
        self.called = True
        self.last_prompt = prompt
        return self.result


@pytest.mark.asyncio
async def test_loop_execute_cycle():
    """trigger -> think returns execute -> act called -> mem0 updated"""
    bus = EventBus()
    bus.subscribe("test-agent")
    mem0 = FakeMem0()
    state_store = DaemonStateStore(InMemoryFileStore())

    decision = Decision(action="execute", task_prompt="check email", reasoning="daily", priority="normal")
    think = MockThinkEngine(decision)
    runtime = MockRuntime("3 emails found")

    loop = AgentLoop(
        agent_name="test-agent",
        event_bus=bus,
        think_engine=think,
        runtime_factory=lambda **kw: runtime,
        daemon_state_store=state_store,
        agent_uuid="test-uuid",
        tracer=NullTracer(),
        mem0_client=mem0,
        goals=[],
    )

    # Push a trigger event
    await bus.publish(AgentEvent(source="cron", type="cron.daily", target_agent="test-agent"))

    # Run one cycle
    await loop.run_once()

    assert think.called
    assert runtime.called
    assert runtime.last_prompt == "check email"

    # Mem0 should have an episode
    assert len(mem0.added) == 1
    assert "check email" in mem0.added[0][0][0]["content"]


@pytest.mark.asyncio
async def test_loop_skip_cycle():
    """trigger -> think returns skip -> act NOT called"""
    bus = EventBus()
    bus.subscribe("test-agent")

    decision = Decision(action="skip", reasoning="nothing to do")
    think = MockThinkEngine(decision)
    runtime = MockRuntime()

    loop = AgentLoop(
        agent_name="test-agent",
        event_bus=bus,
        think_engine=think,
        runtime_factory=lambda **kw: runtime,
        daemon_state_store=DaemonStateStore(InMemoryFileStore()),
        agent_uuid="test-uuid",
        tracer=NullTracer(),
        goals=[],
    )

    await bus.publish(AgentEvent(source="cron", type="tick", target_agent="test-agent"))
    await loop.run_once()

    assert think.called
    assert not runtime.called


@pytest.mark.asyncio
async def test_loop_updates_recent_decisions():
    """After execute, daemon state should have recent decision."""
    bus = EventBus()
    bus.subscribe("test-agent")
    state_store = DaemonStateStore(InMemoryFileStore())

    decision = Decision(action="execute", task_prompt="deploy", reasoning="release day", priority="high")
    think = MockThinkEngine(decision)
    runtime = MockRuntime("deployed v2.0")

    loop = AgentLoop(
        agent_name="test-agent",
        event_bus=bus,
        think_engine=think,
        runtime_factory=lambda **kw: runtime,
        daemon_state_store=state_store,
        agent_uuid="test-uuid",
        tracer=NullTracer(),
        goals=[],
    )

    await bus.publish(AgentEvent(source="cron", type="tick", target_agent="test-agent"))
    await loop.run_once()

    state = await state_store.load("test-uuid")
    assert len(state.recent_decisions) > 0
    assert state.recent_decisions[-1]["action"] == "execute"


@pytest.mark.asyncio
async def test_loop_no_event_returns_without_acting():
    """When no event in queue, run_once should return without doing anything."""
    bus = EventBus()
    bus.subscribe("test-agent")
    think = MockThinkEngine(Decision(action="execute", task_prompt="x", reasoning="y"))
    runtime = MockRuntime()

    loop = AgentLoop(
        agent_name="test-agent",
        event_bus=bus,
        think_engine=think,
        runtime_factory=lambda **kw: runtime,
        daemon_state_store=DaemonStateStore(InMemoryFileStore()),
        agent_uuid="test-uuid",
        tracer=NullTracer(),
        goals=[],
        tick_interval=0.05,
    )

    await loop.run_once()
    assert not think.called
    assert not runtime.called


# ---------------------------------------------------------------------------
# Trace event tests
# ---------------------------------------------------------------------------

class CollectingTracer:
    """Test helper that stores trace events."""
    def __init__(self):
        self.events = []

    def on_event(self, event):
        self.events.append(event)


@pytest.mark.asyncio
async def test_loop_emits_trace_events():
    bus = EventBus()
    bus.subscribe("test-agent")
    tracer = CollectingTracer()

    decision = Decision(action="execute", task_prompt="test task", reasoning="testing", priority="normal")
    think = MockThinkEngine(decision)
    runtime = MockRuntime("done")

    loop = AgentLoop(
        agent_name="test-agent",
        event_bus=bus,
        think_engine=think,
        runtime_factory=lambda **kw: runtime,
        daemon_state_store=DaemonStateStore(InMemoryFileStore()),
        agent_uuid="test-uuid",
        tracer=tracer,
        goals=[],
    )

    await bus.publish(AgentEvent(source="cron", type="tick", target_agent="test-agent"))
    await loop.run_once()

    event_kinds = [e.kind for e in tracer.events]
    assert "loop_wake" in event_kinds
    assert "loop_think_start" in event_kinds
    assert "loop_think_end" in event_kinds
    assert "loop_act_start" in event_kinds
    assert "loop_act_end" in event_kinds
    assert "loop_reflect" in event_kinds


@pytest.mark.asyncio
async def test_loop_skip_emits_think_but_no_act():
    bus = EventBus()
    bus.subscribe("test-agent")
    tracer = CollectingTracer()

    decision = Decision(action="skip", reasoning="nothing to do")
    think = MockThinkEngine(decision)
    runtime = MockRuntime()

    loop = AgentLoop(
        agent_name="test-agent",
        event_bus=bus,
        think_engine=think,
        runtime_factory=lambda **kw: runtime,
        daemon_state_store=DaemonStateStore(InMemoryFileStore()),
        agent_uuid="test-uuid",
        tracer=tracer,
        goals=[],
    )

    await bus.publish(AgentEvent(source="cron", type="tick", target_agent="test-agent"))
    await loop.run_once()

    event_kinds = [e.kind for e in tracer.events]
    assert "loop_wake" in event_kinds
    assert "loop_think_start" in event_kinds
    assert "loop_think_end" in event_kinds
    assert "loop_act_start" not in event_kinds  # skip = no act
    assert "loop_reflect" in event_kinds


# ---------------------------------------------------------------------------
# Channel resolution tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_loop_uses_agent_hitl_channels():
    """Agent-level hitl_channels → scoped ChannelManager passed to runtime."""
    from everstaff.schema.autonomy import HitlChannelRef

    bus = EventBus()
    bus.subscribe("test-agent")

    decision = Decision(action="execute", task_prompt="do work", reasoning="r", priority="normal")
    think = MockThinkEngine(decision)
    received_cm = []

    class _CapturingRuntime:
        async def run(self, prompt: str, **kw) -> str:
            return "done"

    def _factory(**kw):
        received_cm.append(kw.get("channel_manager"))
        return _CapturingRuntime()

    class _FakeChannel:
        async def send_request(self, *a): pass
        async def on_resolved(self, *a): pass
        async def start(self): pass
        async def stop(self): pass

    agent_ch = _FakeChannel()

    loop = AgentLoop(
        agent_name="test-agent",
        event_bus=bus,
        think_engine=think,
        runtime_factory=_factory,
        daemon_state_store=DaemonStateStore(InMemoryFileStore()),
        agent_uuid="test-uuid",
        tracer=NullTracer(),
        hitl_channels=[HitlChannelRef(ref="agent-ch")],
        channel_registry={"agent-ch": agent_ch},
    )

    await bus.publish(AgentEvent(source="cron", type="cron.daily", target_agent="test-agent"))
    await loop.run_once()

    scoped = received_cm[0]
    assert agent_ch in scoped._channels


@pytest.mark.asyncio
async def test_loop_no_hitl_channels_passes_default_cm():
    """No hitl_channels configured → passes default channel_manager to runtime."""
    from everstaff.channels.manager import ChannelManager

    bus = EventBus()
    bus.subscribe("test-agent")

    decision = Decision(action="execute", task_prompt="do work", reasoning="r", priority="normal")
    think = MockThinkEngine(decision)
    received_cm = []

    class _CapturingRuntime:
        async def run(self, prompt: str, **kw) -> str:
            return "done"

    def _factory(**kw):
        received_cm.append(kw.get("channel_manager"))
        return _CapturingRuntime()

    default_cm = ChannelManager()

    loop = AgentLoop(
        agent_name="test-agent",
        event_bus=bus,
        think_engine=think,
        runtime_factory=_factory,
        daemon_state_store=DaemonStateStore(InMemoryFileStore()),
        agent_uuid="test-uuid",
        tracer=NullTracer(),
        channel_manager=default_cm,
        triggers=[],
        hitl_channels=[],
        channel_registry={},
    )

    await bus.publish(AgentEvent(source="cron", type="cron.daily", target_agent="test-agent"))
    await loop.run_once()

    assert received_cm[0] is default_cm


# ---------------------------------------------------------------------------
# Unified session tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_loop_writes_unified_session(tmp_path):
    """Single session.json contains think messages + completion."""
    import json
    from everstaff.protocols import Message
    bus = EventBus()
    bus.subscribe("test-agent")
    state_store = DaemonStateStore(InMemoryFileStore())

    decision = Decision(action="execute", task_prompt="check email", reasoning="daily", priority="normal")
    think_msgs = [
        Message(role="user", content="Trigger received", created_at="2026-01-01T00:00:00Z"),
        Message(role="assistant", content="thinking...", tool_calls=[{"id":"tc-1","type":"function","function":{"name":"make_decision","arguments":"{}"}}], created_at="2026-01-01T00:00:01Z"),
        Message(role="tool", content="Decision 'execute' recorded.", tool_call_id="tc-1", created_at="2026-01-01T00:00:01Z"),
    ]

    class ThinkReturningMessages:
        called = False
        async def think(self, agent_name, trigger, pending_events, autonomy_goals):
            self.called = True
            return decision, think_msgs

    think = ThinkReturningMessages()
    runtime = MockRuntime("3 emails found")

    loop = AgentLoop(
        agent_name="test-agent",
        event_bus=bus,
        think_engine=think,
        runtime_factory=lambda **kw: runtime,
        daemon_state_store=state_store,
        agent_uuid="test-uuid",
        tracer=NullTracer(),
        sessions_dir=str(tmp_path),
    )

    await bus.publish(AgentEvent(source="cron", type="cron.daily", target_agent="test-agent"))
    await loop.run_once()

    # Find the session directory
    session_dirs = [d for d in tmp_path.iterdir() if d.is_dir()]
    assert len(session_dirs) == 1
    session_file = session_dirs[0] / "session.json"
    assert session_file.exists()

    data = json.loads(session_file.read_text())
    assert data["status"] == "completed"
    # Should contain: initial trigger msg + 3 think msgs = 4
    # (runtime saves its own assistant message; _finish_loop_session only sets status)
    assert len(data["messages"]) >= 3
    # No sub_sessions directory should exist
    assert not (session_dirs[0] / "sub_sessions").exists()


@pytest.mark.asyncio
async def test_loop_skip_writes_session_with_think_messages(tmp_path):
    """Skip/defer also produces a session with think messages."""
    import json
    from everstaff.protocols import Message
    bus = EventBus()
    bus.subscribe("test-agent")
    state_store = DaemonStateStore(InMemoryFileStore())

    decision = Decision(action="skip", reasoning="nothing to do")
    think_msgs = [
        Message(role="user", content="Trigger received", created_at="2026-01-01T00:00:00Z"),
        Message(role="assistant", content="Nothing needed", created_at="2026-01-01T00:00:01Z"),
    ]

    class ThinkReturningSkip:
        called = False
        async def think(self, agent_name, trigger, pending_events, autonomy_goals):
            self.called = True
            return decision, think_msgs

    think = ThinkReturningSkip()
    runtime = MockRuntime()

    loop = AgentLoop(
        agent_name="test-agent",
        event_bus=bus,
        think_engine=think,
        runtime_factory=lambda **kw: runtime,
        daemon_state_store=state_store,
        agent_uuid="test-uuid",
        tracer=NullTracer(),
        sessions_dir=str(tmp_path),
    )

    await bus.publish(AgentEvent(source="cron", type="tick", target_agent="test-agent"))
    await loop.run_once()

    session_dirs = [d for d in tmp_path.iterdir() if d.is_dir()]
    assert len(session_dirs) == 1
    data = json.loads((session_dirs[0] / "session.json").read_text())
    assert data["status"] == "completed"
    # Should have think messages even for skip
    assert len(data["messages"]) >= 3  # initial trigger + 2 think msgs + completion

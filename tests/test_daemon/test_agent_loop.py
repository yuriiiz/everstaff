import asyncio
import pytest
from dataclasses import dataclass
from everstaff.daemon.agent_loop import AgentLoop
from everstaff.daemon.event_bus import EventBus
from everstaff.daemon.think_engine import ThinkEngine
from everstaff.protocols import AgentEvent, Decision, Episode, WorkingState, LLMResponse, ToolCallRequest
from everstaff.nulls import InMemoryStore, NullTracer


class MockThinkEngine:
    """Returns a fixed decision."""
    def __init__(self, decision: Decision):
        self.decision = decision
        self.called = False

    async def think(self, agent_name, trigger, pending_events, autonomy_goals, parent_session_id):
        self.called = True
        return self.decision


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
    """trigger -> think returns execute -> act called -> memory updated"""
    bus = EventBus()
    bus.subscribe("test-agent")
    memory = InMemoryStore()

    decision = Decision(action="execute", task_prompt="check email", reasoning="daily", priority="normal")
    think = MockThinkEngine(decision)
    runtime = MockRuntime("3 emails found")

    loop = AgentLoop(
        agent_name="test-agent",
        event_bus=bus,
        think_engine=think,
        runtime_factory=lambda **kw: runtime,
        memory=memory,
        tracer=NullTracer(),
        autonomy_level="autonomous",
        goals=[],
    )

    # Push a trigger event
    await bus.publish(AgentEvent(source="cron", type="cron.daily", target_agent="test-agent"))

    # Run one cycle
    await loop.run_once()

    assert think.called
    assert runtime.called
    assert runtime.last_prompt == "check email"

    # Memory should have an episode
    episodes = await memory.episode_query("test-agent")
    assert len(episodes) == 1
    assert episodes[0].action == "check email"
    assert episodes[0].result == "3 emails found"


@pytest.mark.asyncio
async def test_loop_skip_cycle():
    """trigger -> think returns skip -> act NOT called"""
    bus = EventBus()
    bus.subscribe("test-agent")
    memory = InMemoryStore()

    decision = Decision(action="skip", reasoning="nothing to do")
    think = MockThinkEngine(decision)
    runtime = MockRuntime()

    loop = AgentLoop(
        agent_name="test-agent",
        event_bus=bus,
        think_engine=think,
        runtime_factory=lambda **kw: runtime,
        memory=memory,
        tracer=NullTracer(),
        autonomy_level="autonomous",
        goals=[],
    )

    await bus.publish(AgentEvent(source="cron", type="tick", target_agent="test-agent"))
    await loop.run_once()

    assert think.called
    assert not runtime.called


@pytest.mark.asyncio
async def test_loop_updates_working_memory():
    """After execute, working memory should have recent decision."""
    bus = EventBus()
    bus.subscribe("test-agent")
    memory = InMemoryStore()

    decision = Decision(action="execute", task_prompt="deploy", reasoning="release day", priority="high")
    think = MockThinkEngine(decision)
    runtime = MockRuntime("deployed v2.0")

    loop = AgentLoop(
        agent_name="test-agent",
        event_bus=bus,
        think_engine=think,
        runtime_factory=lambda **kw: runtime,
        memory=memory,
        tracer=NullTracer(),
        autonomy_level="autonomous",
        goals=[],
    )

    await bus.publish(AgentEvent(source="cron", type="tick", target_agent="test-agent"))
    await loop.run_once()

    ws = await memory.working_load("test-agent")
    assert len(ws.recent_decisions) > 0
    assert ws.recent_decisions[-1]["action"] == "execute"


@pytest.mark.asyncio
async def test_loop_no_event_returns_without_acting():
    """When no event in queue, run_once should return without doing anything."""
    bus = EventBus()
    bus.subscribe("test-agent")
    memory = InMemoryStore()
    think = MockThinkEngine(Decision(action="execute", task_prompt="x", reasoning="y"))
    runtime = MockRuntime()

    loop = AgentLoop(
        agent_name="test-agent",
        event_bus=bus,
        think_engine=think,
        runtime_factory=lambda **kw: runtime,
        memory=memory,
        tracer=NullTracer(),
        autonomy_level="autonomous",
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
    memory = InMemoryStore()
    tracer = CollectingTracer()

    decision = Decision(action="execute", task_prompt="test task", reasoning="testing", priority="normal")
    think = MockThinkEngine(decision)
    runtime = MockRuntime("done")

    loop = AgentLoop(
        agent_name="test-agent",
        event_bus=bus,
        think_engine=think,
        runtime_factory=lambda **kw: runtime,
        memory=memory,
        tracer=tracer,
        autonomy_level="autonomous",
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
    memory = InMemoryStore()
    tracer = CollectingTracer()

    decision = Decision(action="skip", reasoning="nothing to do")
    think = MockThinkEngine(decision)
    runtime = MockRuntime()

    loop = AgentLoop(
        agent_name="test-agent",
        event_bus=bus,
        think_engine=think,
        runtime_factory=lambda **kw: runtime,
        memory=memory,
        tracer=tracer,
        autonomy_level="autonomous",
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
async def test_loop_uses_trigger_hitl_channels():
    """When trigger has hitl_channels, scoped ChannelManager passed to runtime."""
    from everstaff.schema.autonomy import TriggerConfig, HitlChannelRef
    from everstaff.channels.manager import ChannelManager

    bus = EventBus()
    bus.subscribe("test-agent")
    memory = InMemoryStore()

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

    fake_ch = _FakeChannel()
    trigger = TriggerConfig(
        id="daily",
        type="cron",
        schedule="* * * * *",
        task="do work",
        hitl_channels=[HitlChannelRef(ref="lark-main")],
    )

    loop = AgentLoop(
        agent_name="test-agent",
        event_bus=bus,
        think_engine=think,
        runtime_factory=_factory,
        memory=memory,
        tracer=NullTracer(),
        autonomy_level="autonomous",
        triggers=[trigger],
        agent_hitl_channels=[],
        channel_registry={"lark-main": fake_ch},
    )

    await bus.publish(AgentEvent(source="cron", type="cron.daily", target_agent="test-agent"))
    await loop.run_once()

    assert len(received_cm) == 1
    scoped = received_cm[0]
    assert scoped is not None
    assert fake_ch in scoped._channels


@pytest.mark.asyncio
async def test_loop_falls_back_to_agent_hitl_channels():
    """Trigger without hitl_channels falls back to agent-level hitl_channels."""
    from everstaff.schema.autonomy import TriggerConfig, HitlChannelRef

    bus = EventBus()
    bus.subscribe("test-agent")
    memory = InMemoryStore()

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
    trigger = TriggerConfig(
        id="daily", type="cron", schedule="* * * * *", task="do work",
        hitl_channels=None,
    )

    loop = AgentLoop(
        agent_name="test-agent",
        event_bus=bus,
        think_engine=think,
        runtime_factory=_factory,
        memory=memory,
        tracer=NullTracer(),
        autonomy_level="autonomous",
        triggers=[trigger],
        agent_hitl_channels=[HitlChannelRef(ref="agent-ch")],
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
    memory = InMemoryStore()

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
        memory=memory,
        tracer=NullTracer(),
        autonomy_level="autonomous",
        channel_manager=default_cm,
        triggers=[],
        agent_hitl_channels=[],
        channel_registry={},
    )

    await bus.publish(AgentEvent(source="cron", type="cron.daily", target_agent="test-agent"))
    await loop.run_once()

    assert received_cm[0] is default_cm

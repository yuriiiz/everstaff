import pytest
from everstaff.daemon.think_engine import ThinkEngine, ThinkToolContext, THINK_TOOL_CLASSES, _build_think_registry, _build_breakdown_registry
from everstaff.daemon.state_store import DaemonState, DaemonStateStore
from everstaff.daemon.goals import GoalBreakdown, SubGoal
from everstaff.schema.autonomy import GoalConfig
from everstaff.protocols import AgentEvent, Decision, Message, LLMResponse, ToolCallRequest
from everstaff.nulls import NullTracer


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


class FakeLLM:
    def __init__(self, decision_args: dict):
        self._decision_args = decision_args
        self.call_count = 0

    async def complete(self, messages, tools, system=None):
        self.call_count += 1
        return LLMResponse(
            content=None,
            tool_calls=[ToolCallRequest(
                id="tc-1", name="make_decision", args=self._decision_args,
            )],
        )


class FakeMem0:
    def __init__(self):
        self.added: list[tuple] = []
        self.searched: list[str] = []

    async def add(self, messages, **scope):
        self.added.append((messages, scope))
        return []

    async def search(self, query, *, top_k=None, **scope):
        self.searched.append(query)
        return [{"memory": "relevant context", "score": 0.9}]


@pytest.mark.asyncio
async def test_think_returns_decision_and_messages():
    state_store = DaemonStateStore(InMemoryFileStore())
    llm = FakeLLM({"action": "execute", "task_prompt": "check email", "reasoning": "daily", "priority": "normal"})
    engine = ThinkEngine(
        llm_client=llm,
        tracer=NullTracer(),
        daemon_state_store=state_store,
        agent_uuid="test-uuid",
    )
    trigger = AgentEvent(source="cron", type="cron.daily")
    decision, messages = await engine.think(
        agent_name="test",
        trigger=trigger,
        pending_events=[],
        autonomy_goals=[],
    )
    assert decision.action == "execute"
    assert decision.task_prompt == "check email"
    assert len(messages) > 0
    assert messages[0].role == "user"


@pytest.mark.asyncio
async def test_think_with_search_memory():
    """LLM first searches memory via mem0, then makes decision."""
    state_store = DaemonStateStore(InMemoryFileStore())
    mem0 = FakeMem0()
    call_num = 0

    class SearchThenDecideLLM:
        async def complete(self, messages, tools, system=None):
            nonlocal call_num
            call_num += 1
            if call_num == 1:
                return LLMResponse(content=None, tool_calls=[
                    ToolCallRequest(id="tc-1", name="search_memory", args={"query": "past patterns"}),
                ])
            return LLMResponse(content=None, tool_calls=[
                ToolCallRequest(id="tc-2", name="make_decision", args={
                    "action": "execute", "task_prompt": "review PRs", "reasoning": "pattern match", "priority": "normal",
                }),
            ])

    engine = ThinkEngine(
        llm_client=SearchThenDecideLLM(),
        tracer=NullTracer(),
        daemon_state_store=state_store,
        agent_uuid="test-uuid",
        mem0_client=mem0,
    )
    trigger = AgentEvent(source="cron", type="cron.daily")
    decision, messages = await engine.think("test", trigger, [], [])
    assert decision.action == "execute"
    assert "PRs" in decision.task_prompt
    assert call_num == 2
    assert mem0.searched == ["past patterns"]


@pytest.mark.asyncio
async def test_think_no_tool_call_returns_skip():
    state_store = DaemonStateStore(InMemoryFileStore())

    class NoToolLLM:
        async def complete(self, messages, tools, system=None):
            return LLMResponse(content="I have nothing to do")

    engine = ThinkEngine(
        llm_client=NoToolLLM(),
        tracer=NullTracer(),
        daemon_state_store=state_store,
        agent_uuid="test-uuid",
    )
    trigger = AgentEvent(source="internal", type="tick")
    decision, messages = await engine.think("test", trigger, [], [])
    assert decision.action == "skip"


def test_think_tool_classes_have_expected_tools():
    """Every expected tool name is present in THINK_TOOL_CLASSES."""
    ctx = ThinkToolContext(agent_name="t", agent_uuid="u", state=None, state_store=None, mem0=None)
    names = {cls(ctx).definition.name for cls in THINK_TOOL_CLASSES}
    assert names == {"make_decision", "search_memory", "break_down_goal", "update_goal_progress", "record_learning_insight"}


def test_build_think_registry_returns_all_tools():
    """_build_think_registry creates a registry with all think tools."""
    ctx = ThinkToolContext(agent_name="t", agent_uuid="u", state=None, state_store=None, mem0=None)
    registry = _build_think_registry(ctx)
    defns = registry.get_definitions()
    names = {d.name for d in defns}
    assert names == {"make_decision", "search_memory", "break_down_goal", "update_goal_progress", "record_learning_insight"}


@pytest.mark.asyncio
async def test_search_memory_disabled_when_no_mem0():
    state_store = DaemonStateStore(InMemoryFileStore())
    call_num = 0

    class SearchThenDecideLLM:
        async def complete(self, messages, tools, system=None):
            nonlocal call_num
            call_num += 1
            if call_num == 1:
                return LLMResponse(content=None, tool_calls=[
                    ToolCallRequest(id="tc-1", name="search_memory", args={"query": "anything"}),
                ])
            tool_msgs = [m for m in messages if m.role == "tool"]
            assert any("not enabled" in (m.content or "") for m in tool_msgs)
            return LLMResponse(content=None, tool_calls=[
                ToolCallRequest(id="tc-2", name="make_decision", args={
                    "action": "skip", "reasoning": "no memory",
                }),
            ])

    engine = ThinkEngine(
        llm_client=SearchThenDecideLLM(),
        tracer=NullTracer(),
        daemon_state_store=state_store,
        agent_uuid="test-uuid",
        mem0_client=None,
    )
    trigger = AgentEvent(source="cron", type="cron.daily")
    decision, messages = await engine.think("test", trigger, [], [])
    assert decision.action == "skip"


@pytest.mark.asyncio
async def test_break_down_goal_uses_state_store():
    fs = InMemoryFileStore()
    state_store = DaemonStateStore(fs)
    call_num = 0

    class GoalThenDecideLLM:
        async def complete(self, messages, tools, system=None):
            nonlocal call_num
            call_num += 1
            if call_num == 1:
                return LLMResponse(content=None, tool_calls=[
                    ToolCallRequest(id="tc-1", name="break_down_goal", args={
                        "goal_id": "g1",
                        "sub_goals": [
                            {"description": "step 1", "acceptance_criteria": "done"},
                            {"description": "step 2"},
                        ],
                    }),
                ])
            return LLMResponse(content=None, tool_calls=[
                ToolCallRequest(id="tc-2", name="make_decision", args={
                    "action": "execute", "reasoning": "goals set", "task_prompt": "do step 1",
                }),
            ])

    engine = ThinkEngine(
        llm_client=GoalThenDecideLLM(),
        tracer=NullTracer(),
        daemon_state_store=state_store,
        agent_uuid="test-uuid",
    )
    trigger = AgentEvent(source="cron", type="cron.daily")
    await engine.think("test", trigger, [], [])

    state = await state_store.load("test-uuid")
    assert "g1" in state.goals_breakdown
    assert len(state.goals_breakdown["g1"].sub_goals) == 2


@pytest.mark.asyncio
async def test_record_learning_insight_uses_mem0():
    fs = InMemoryFileStore()
    state_store = DaemonStateStore(fs)
    mem0 = FakeMem0()
    call_num = 0

    class InsightThenDecideLLM:
        async def complete(self, messages, tools, system=None):
            nonlocal call_num
            call_num += 1
            if call_num == 1:
                return LLMResponse(content=None, tool_calls=[
                    ToolCallRequest(id="tc-1", name="record_learning_insight", args={
                        "category": "pattern",
                        "insight": "Mondays are slow",
                        "evidence": "ep-1, ep-2",
                        "action": "schedule less on Mondays",
                    }),
                ])
            return LLMResponse(content=None, tool_calls=[
                ToolCallRequest(id="tc-2", name="make_decision", args={
                    "action": "skip", "reasoning": "done",
                }),
            ])

    engine = ThinkEngine(
        llm_client=InsightThenDecideLLM(),
        tracer=NullTracer(),
        daemon_state_store=state_store,
        agent_uuid="test-uuid",
        mem0_client=mem0,
    )
    trigger = AgentEvent(source="internal", type="internal.reflect")
    await engine.think("test", trigger, [], [])

    assert len(mem0.added) == 1
    content = mem0.added[0][0][0]["content"]
    assert "pattern" in content
    assert "Mondays are slow" in content


# ---------------------------------------------------------------------------
# _ensure_breakdowns tests
# ---------------------------------------------------------------------------


def test_build_breakdown_registry_only_has_break_down_goal():
    ctx = ThinkToolContext(agent_name="t", agent_uuid="u", state=None, state_store=None, mem0=None)
    registry = _build_breakdown_registry(ctx)
    names = {d.name for d in registry.get_definitions()}
    assert names == {"break_down_goal"}


@pytest.mark.asyncio
async def test_ensure_breakdowns_runs_for_missing_goals():
    """When goals lack breakdowns, the pre-phase LLM call produces them."""
    fs = InMemoryFileStore()
    state_store = DaemonStateStore(fs)
    call_num = 0

    class BreakdownLLM:
        async def complete(self, messages, tools, system=None):
            nonlocal call_num
            call_num += 1
            # First call: break down g1, second: break down g2, third: make_decision
            tool_names = {t.name for t in tools}
            if "break_down_goal" in tool_names and "make_decision" not in tool_names:
                # Breakdown phase — return breakdowns for both goals at once
                return LLMResponse(content=None, tool_calls=[
                    ToolCallRequest(id=f"tc-bd-{call_num}-a", name="break_down_goal", args={
                        "goal_id": "g1",
                        "sub_goals": [{"description": "g1 step 1"}, {"description": "g1 step 2"}],
                    }),
                    ToolCallRequest(id=f"tc-bd-{call_num}-b", name="break_down_goal", args={
                        "goal_id": "g2",
                        "sub_goals": [{"description": "g2 step 1"}],
                    }),
                ])
            # Main think phase — just decide
            return LLMResponse(content=None, tool_calls=[
                ToolCallRequest(id="tc-dec", name="make_decision", args={
                    "action": "execute", "reasoning": "goals ready", "task_prompt": "do g1 step 1",
                }),
            ])

    goals = [
        GoalConfig(id="g1", description="First goal", priority="high"),
        GoalConfig(id="g2", description="Second goal", priority="normal"),
    ]
    engine = ThinkEngine(
        llm_client=BreakdownLLM(),
        tracer=NullTracer(),
        daemon_state_store=state_store,
        agent_uuid="test-uuid",
    )
    trigger = AgentEvent(source="cron", type="cron.daily")
    decision, messages = await engine.think("test", trigger, [], goals)

    # Breakdowns should be persisted
    state = await state_store.load("test-uuid")
    assert "g1" in state.goals_breakdown
    assert "g2" in state.goals_breakdown
    assert len(state.goals_breakdown["g1"].sub_goals) == 2
    assert len(state.goals_breakdown["g2"].sub_goals) == 1

    # Decision should still be made
    assert decision.action == "execute"


@pytest.mark.asyncio
async def test_ensure_breakdowns_skips_when_all_present():
    """When all goals already have breakdowns, no extra LLM call is made."""
    fs = InMemoryFileStore()
    state_store = DaemonStateStore(fs)

    # Pre-populate breakdown for g1
    state = DaemonState()
    state.goals_breakdown["g1"] = GoalBreakdown(
        goal_id="g1",
        sub_goals=[SubGoal(description="step 1")],
    )
    await state_store.save("test-uuid", state)

    call_count = 0

    class CountingLLM:
        async def complete(self, messages, tools, system=None):
            nonlocal call_count
            call_count += 1
            return LLMResponse(content=None, tool_calls=[
                ToolCallRequest(id="tc-1", name="make_decision", args={
                    "action": "skip", "reasoning": "all good",
                }),
            ])

    goals = [GoalConfig(id="g1", description="First goal")]
    engine = ThinkEngine(
        llm_client=CountingLLM(),
        tracer=NullTracer(),
        daemon_state_store=state_store,
        agent_uuid="test-uuid",
    )
    trigger = AgentEvent(source="cron", type="cron.daily")
    await engine.think("test", trigger, [], goals)

    # Only 1 call (the main think loop), no breakdown phase
    assert call_count == 1


@pytest.mark.asyncio
async def test_ensure_breakdowns_only_for_missing():
    """Only goals without existing breakdowns trigger the pre-phase."""
    fs = InMemoryFileStore()
    state_store = DaemonStateStore(fs)

    # Pre-populate breakdown for g1 only
    state = DaemonState()
    state.goals_breakdown["g1"] = GoalBreakdown(
        goal_id="g1",
        sub_goals=[SubGoal(description="existing step")],
    )
    await state_store.save("test-uuid", state)

    breakdown_calls = []

    class SelectiveBreakdownLLM:
        async def complete(self, messages, tools, system=None):
            tool_names = {t.name for t in tools}
            if "break_down_goal" in tool_names and "make_decision" not in tool_names:
                # Breakdown phase — should only be asked about g2
                assert "g2" in (system or "")
                breakdown_calls.append("g2")
                return LLMResponse(content=None, tool_calls=[
                    ToolCallRequest(id="tc-bd", name="break_down_goal", args={
                        "goal_id": "g2",
                        "sub_goals": [{"description": "g2 step 1"}],
                    }),
                ])
            return LLMResponse(content=None, tool_calls=[
                ToolCallRequest(id="tc-dec", name="make_decision", args={
                    "action": "skip", "reasoning": "done",
                }),
            ])

    goals = [
        GoalConfig(id="g1", description="First goal"),
        GoalConfig(id="g2", description="Second goal"),
    ]
    engine = ThinkEngine(
        llm_client=SelectiveBreakdownLLM(),
        tracer=NullTracer(),
        daemon_state_store=state_store,
        agent_uuid="test-uuid",
    )
    trigger = AgentEvent(source="cron", type="cron.daily")
    await engine.think("test", trigger, [], goals)

    state = await state_store.load("test-uuid")
    assert "g1" in state.goals_breakdown
    assert "g2" in state.goals_breakdown
    assert breakdown_calls == ["g2"]


@pytest.mark.asyncio
async def test_system_prompt_includes_review_instruction():
    """When breakdowns exist, system prompt tells LLM to review them."""
    fs = InMemoryFileStore()
    state_store = DaemonStateStore(fs)

    # Pre-populate a breakdown
    state = DaemonState()
    state.goals_breakdown["g1"] = GoalBreakdown(
        goal_id="g1",
        sub_goals=[SubGoal(description="step 1")],
    )
    await state_store.save("test-uuid", state)

    captured_system = []

    class CaptureLLM:
        async def complete(self, messages, tools, system=None):
            captured_system.append(system)
            return LLMResponse(content=None, tool_calls=[
                ToolCallRequest(id="tc-1", name="make_decision", args={
                    "action": "skip", "reasoning": "ok",
                }),
            ])

    goals = [GoalConfig(id="g1", description="First goal")]
    engine = ThinkEngine(
        llm_client=CaptureLLM(),
        tracer=NullTracer(),
        daemon_state_store=state_store,
        agent_uuid="test-uuid",
    )
    trigger = AgentEvent(source="cron", type="cron.daily")
    await engine.think("test", trigger, [], goals)

    assert any("Review existing goal breakdowns" in (s or "") for s in captured_system)

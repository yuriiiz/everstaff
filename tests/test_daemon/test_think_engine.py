import pytest
from everstaff.daemon.think_engine import ThinkEngine, THINK_TOOLS, THINK_TOOL_HANDLERS, ThinkToolContext
from everstaff.daemon.state_store import DaemonState, DaemonStateStore
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
async def test_think_returns_decision():
    state_store = DaemonStateStore(InMemoryFileStore())
    llm = FakeLLM({"action": "execute", "task_prompt": "check email", "reasoning": "daily", "priority": "normal"})
    engine = ThinkEngine(
        llm_client=llm,
        tracer=NullTracer(),
        daemon_state_store=state_store,
        agent_uuid="test-uuid",
    )
    trigger = AgentEvent(source="cron", type="cron.daily")
    decision = await engine.think(
        agent_name="test",
        trigger=trigger,
        pending_events=[],
        autonomy_goals=[],
        parent_session_id="loop-123",
    )
    assert decision.action == "execute"
    assert decision.task_prompt == "check email"


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
    decision = await engine.think("test", trigger, [], [], "loop-123")
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
    decision = await engine.think("test", trigger, [], [], "loop-123")
    assert decision.action == "skip"


def test_think_tools_have_expected_tools():
    names = [t.name for t in THINK_TOOLS]
    assert "make_decision" in names
    assert "search_memory" in names
    assert "break_down_goal" in names
    assert "update_goal_progress" in names
    assert "record_learning_insight" in names
    # Old tools removed
    assert "recall_semantic_detail" not in names
    assert "recall_recent_episodes" not in names


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
    decision = await engine.think("test", trigger, [], [], "loop-123")
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
    await engine.think("test", trigger, [], [], "loop-123")

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
    await engine.think("test", trigger, [], [], "loop-123")

    assert len(mem0.added) == 1
    content = mem0.added[0][0][0]["content"]
    assert "pattern" in content
    assert "Mondays are slow" in content


def test_think_tool_handlers_match_definitions():
    """Every THINK_TOOLS entry has a matching handler."""
    tool_names = {t.name for t in THINK_TOOLS}
    handler_names = set(THINK_TOOL_HANDLERS.keys())
    assert tool_names == handler_names

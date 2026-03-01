import pytest
from everstaff.daemon.think_engine import ThinkEngine, THINK_TOOLS
from everstaff.protocols import AgentEvent, Decision, WorkingState, Episode, Message, LLMResponse, ToolCallRequest
from everstaff.nulls import InMemoryStore, NullTracer


class FakeLLM:
    """Returns a make_decision tool call on first complete()."""
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


@pytest.mark.asyncio
async def test_think_returns_decision():
    memory = InMemoryStore()
    llm = FakeLLM({"action": "execute", "task_prompt": "check email", "reasoning": "daily", "priority": "normal"})
    engine = ThinkEngine(llm_client=llm, memory=memory, tracer=NullTracer())

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
async def test_think_with_recall():
    """LLM first recalls memory, then makes decision."""
    memory = InMemoryStore()
    await memory.semantic_write("test", "patterns", "Monday = review PRs")

    call_num = 0

    class RecallThenDecideLLM:
        async def complete(self, messages, tools, system=None):
            nonlocal call_num
            call_num += 1
            if call_num == 1:
                return LLMResponse(content=None, tool_calls=[
                    ToolCallRequest(id="tc-1", name="recall_semantic_detail", args={"topic": "patterns"}),
                ])
            return LLMResponse(content=None, tool_calls=[
                ToolCallRequest(id="tc-2", name="make_decision", args={
                    "action": "execute", "task_prompt": "review PRs", "reasoning": "pattern match", "priority": "normal",
                }),
            ])

    engine = ThinkEngine(llm_client=RecallThenDecideLLM(), memory=memory, tracer=NullTracer())
    trigger = AgentEvent(source="cron", type="cron.daily")
    decision = await engine.think("test", trigger, [], [], "loop-123")
    assert decision.action == "execute"
    assert "PRs" in decision.task_prompt
    assert call_num == 2


@pytest.mark.asyncio
async def test_think_no_tool_call_returns_skip():
    """If LLM returns no tool calls, default to skip."""
    memory = InMemoryStore()

    class NoToolLLM:
        async def complete(self, messages, tools, system=None):
            return LLMResponse(content="I have nothing to do")

    engine = ThinkEngine(llm_client=NoToolLLM(), memory=memory, tracer=NullTracer())
    trigger = AgentEvent(source="internal", type="tick")
    decision = await engine.think("test", trigger, [], [], "loop-123")
    assert decision.action == "skip"


def test_think_tools_have_make_decision():
    names = [t.name for t in THINK_TOOLS]
    assert "make_decision" in names
    assert "recall_semantic_detail" in names
    assert "recall_recent_episodes" in names

# Daemon Memory Redesign — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace daemon's broken L1/L2/L3 memory usage with mem0 + DaemonStateStore.

**Architecture:** DaemonStateStore (JSON via FileStore) handles structured state (goal breakdowns, recent decisions). Mem0Client handles semantic storage (episodes, learning insights) and retrieval (search_memory tool). ThinkEngine and AgentLoop constructors change from `memory: MemoryStore` to `daemon_state_store: DaemonStateStore` + `mem0_client: Mem0Client | None`.

**Tech Stack:** Python 3.12, Pydantic v2, asyncio, FileStore protocol, mem0 SDK

**Design doc:** `docs/plans/2026-03-07-daemon-memory-redesign.md`

---

### Task 1: Create DaemonStateStore

**Files:**
- Create: `src/everstaff/daemon/state_store.py`
- Test: `tests/test_daemon/test_state_store.py`

**Step 1: Write the failing tests**

```python
# tests/test_daemon/test_state_store.py
"""Tests for DaemonStateStore — structured daemon state persistence."""
import json
import pytest
from everstaff.daemon.state_store import DaemonState, DaemonStateStore
from everstaff.daemon.goals import GoalBreakdown, SubGoal


class InMemoryFileStore:
    """Minimal FileStore for testing."""
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


@pytest.mark.asyncio
async def test_load_returns_empty_state_when_not_exists():
    store = DaemonStateStore(InMemoryFileStore())
    state = await store.load("agent-uuid-1")
    assert state.goals_breakdown == {}
    assert state.recent_decisions == []


@pytest.mark.asyncio
async def test_save_and_load_roundtrip():
    fs = InMemoryFileStore()
    store = DaemonStateStore(fs)
    state = DaemonState()
    state.goals_breakdown["g1"] = GoalBreakdown(
        goal_id="g1",
        sub_goals=[SubGoal(description="step 1", status="completed")],
    )
    state.recent_decisions.append({"action": "execute", "task": "test"})
    await store.save("agent-uuid-1", state)

    loaded = await store.load("agent-uuid-1")
    assert "g1" in loaded.goals_breakdown
    assert loaded.goals_breakdown["g1"].goal_id == "g1"
    assert len(loaded.goals_breakdown["g1"].sub_goals) == 1
    assert loaded.recent_decisions == [{"action": "execute", "task": "test"}]


@pytest.mark.asyncio
async def test_state_stored_at_correct_path():
    fs = InMemoryFileStore()
    store = DaemonStateStore(fs)
    await store.save("my-uuid", DaemonState())
    assert await fs.exists("daemon/my-uuid/state.json")


@pytest.mark.asyncio
async def test_daemon_state_goals_breakdown_uses_goal_breakdown_model():
    state = DaemonState()
    gb = GoalBreakdown(goal_id="g1", sub_goals=[
        SubGoal(description="a", status="completed"),
        SubGoal(description="b", status="pending"),
    ])
    state.goals_breakdown["g1"] = gb
    assert state.goals_breakdown["g1"].completion_ratio == pytest.approx(0.5)
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_daemon/test_state_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'everstaff.daemon.state_store'`

**Step 3: Write minimal implementation**

```python
# src/everstaff/daemon/state_store.py
"""DaemonStateStore — structured daemon state persistence via FileStore."""
from __future__ import annotations

import json
import logging
from typing import Any, TYPE_CHECKING

from pydantic import BaseModel, Field

from everstaff.daemon.goals import GoalBreakdown

if TYPE_CHECKING:
    from everstaff.protocols import FileStore

logger = logging.getLogger(__name__)


class DaemonState(BaseModel):
    goals_breakdown: dict[str, GoalBreakdown] = Field(default_factory=dict)
    recent_decisions: list[dict[str, Any]] = Field(default_factory=list)


class DaemonStateStore:
    def __init__(self, store: "FileStore") -> None:
        self._store = store

    def _path(self, agent_uuid: str) -> str:
        return f"daemon/{agent_uuid}/state.json"

    async def load(self, agent_uuid: str) -> DaemonState:
        path = self._path(agent_uuid)
        if not await self._store.exists(path):
            return DaemonState()
        data = await self._store.read(path)
        return DaemonState.model_validate_json(data)

    async def save(self, agent_uuid: str, state: DaemonState) -> None:
        path = self._path(agent_uuid)
        await self._store.write(path, state.model_dump_json(indent=2).encode())
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_daemon/test_state_store.py -v`
Expected: PASS (4 tests)

**Step 5: Commit**

```bash
git add src/everstaff/daemon/state_store.py tests/test_daemon/test_state_store.py
git commit -m "feat(daemon): add DaemonStateStore for structured state persistence"
```

---

### Task 2: Update ThinkEngine — replace memory with DaemonStateStore + Mem0Client

**Files:**
- Modify: `src/everstaff/daemon/think_engine.py`
- Modify: `tests/test_daemon/test_think_engine.py`

**Step 1: Update tests for new ThinkEngine API**

Replace the full test file:

```python
# tests/test_daemon/test_think_engine.py
import pytest
from everstaff.daemon.think_engine import ThinkEngine, THINK_TOOLS
from everstaff.daemon.state_store import DaemonState, DaemonStateStore
from everstaff.protocols import AgentEvent, Decision, Message, LLMResponse, ToolCallRequest
from everstaff.nulls import NullTracer


# -- Reuse InMemoryFileStore from test_state_store --
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


class FakeMem0:
    """Minimal Mem0Client stand-in for testing."""
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
    """search_memory returns graceful message when mem0_client is None."""
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
            # Check that tool response indicates memory not enabled
            tool_msgs = [m for m in messages if m.role == "tool"]
            assert any("not enabled" in (m.content or "") for m in tool_msgs)
            return LLMResponse(content=None, tool_calls=[
                ToolCallRequest(id="tc-2", name="make_decision", args={
                    "action": "skip", "reasoning": "no memory", "priority": "normal",
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
    """break_down_goal tool persists to DaemonStateStore, not working memory."""
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

    # Verify state was persisted
    state = await state_store.load("test-uuid")
    assert "g1" in state.goals_breakdown
    assert len(state.goals_breakdown["g1"].sub_goals) == 2


@pytest.mark.asyncio
async def test_record_learning_insight_uses_mem0():
    """record_learning_insight calls mem0.add() when available."""
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
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_daemon/test_think_engine.py -v`
Expected: FAIL — ThinkEngine constructor doesn't accept `daemon_state_store`

**Step 3: Implement ThinkEngine changes**

Key changes to `src/everstaff/daemon/think_engine.py`:

1. **THINK_TOOLS**: Remove `recall_semantic_detail` and `recall_recent_episodes`. Add `search_memory`.
2. **Constructor**: Replace `memory` with `daemon_state_store`, `agent_uuid`, `mem0_client`.
3. **`think()` method**: Remove memory layer loading (lines 200-207). Load from `DaemonStateStore` instead.
4. **Tool handlers**: Replace `recall_semantic_detail`/`recall_recent_episodes` with `search_memory`. Update `break_down_goal`/`update_goal_progress` to use DaemonStateStore. Update `record_learning_insight` to use mem0.
5. **`_build_system_prompt()`**: Remove `working`, `episodes`, `topics` params. Accept `state: DaemonState` instead.

Detailed changes:

- Lines 64-96: Replace `recall_semantic_detail` and `recall_recent_episodes` tool definitions with:
  ```python
  ToolDefinition(
      name="search_memory",
      description="Search long-term memory for relevant historical context (past episodes, patterns, insights).",
      parameters={
          "type": "object",
          "properties": {
              "query": {"type": "string", "description": "What to search for"},
          },
          "required": ["query"],
      },
  ),
  ```

- Line 168: Change constructor:
  ```python
  def __init__(self, llm_client, tracer, daemon_state_store, agent_uuid, mem0_client=None, sessions_dir=None, session_index=None):
      self._llm = llm_client
      self._tracer = tracer
      self._state_store = daemon_state_store
      self._agent_uuid = agent_uuid
      self._mem0 = mem0_client
      self._sessions_dir = Path(sessions_dir) if sessions_dir else None
      self._session_index = session_index
  ```

- Lines 200-211: Replace memory loading with:
  ```python
  state = await self._state_store.load(self._agent_uuid)
  system_prompt = self._build_system_prompt(agent_name, trigger, pending_events, state, autonomy_goals)
  ```

- Lines 279-306: Replace `recall_semantic_detail` and `recall_recent_episodes` handlers with `search_memory`:
  ```python
  elif tc.name == "search_memory":
      query = tc.args.get("query", "")
      if self._mem0 is None:
          content = "(memory not enabled)"
      else:
          results = await self._mem0.search(query, agent_id=agent_name)
          content = "\n".join(r.get("memory", str(r)) for r in results) or "(no results)"
      messages.append(Message(role="tool", content=content, tool_call_id=tc.id, created_at=...))
  ```

- Lines 308-328: Update `break_down_goal` to use DaemonStateStore:
  ```python
  elif tc.name == "break_down_goal":
      goal_id = tc.args["goal_id"]
      raw_subs = tc.args.get("sub_goals", [])
      sub_goals = [SubGoal(description=s["description"], acceptance_criteria=s.get("acceptance_criteria", "")) for s in raw_subs]
      gb = GoalBreakdown(goal_id=goal_id, sub_goals=sub_goals)
      state.goals_breakdown[goal_id] = gb
      await self._state_store.save(self._agent_uuid, state)
      messages.append(Message(role="tool", content=f"Goal '{goal_id}' broken into {len(sub_goals)} sub-goals.", tool_call_id=tc.id, created_at=...))
  ```

- Lines 330-356: Update `update_goal_progress` similarly (use `state.goals_breakdown` instead of `working.custom`).

- Lines 358-373: Update `record_learning_insight`:
  ```python
  elif tc.name == "record_learning_insight":
      args = tc.args
      if self._mem0 is None:
          result_text = "(memory not enabled, insight not persisted)"
      else:
          content = f"[{args['category']}] {args['insight']} (evidence: {args['evidence']})"
          if args.get("action"):
              content += f" -> action: {args['action']}"
          await self._mem0.add([{"role": "assistant", "content": content}], agent_id=agent_name)
          result_text = "Insight recorded."
      messages.append(Message(role="tool", content=result_text, tool_call_id=tc.id, created_at=...))
  ```

- Lines 468-526: Simplify `_build_system_prompt`:
  ```python
  def _build_system_prompt(self, agent_name, trigger, pending_events, state: DaemonState, goals):
      # Remove episodes/topics/working params
      # Keep: trigger, pending_events, goals, goal breakdowns from state, recent decisions from state
      # Remove: episodes section, topics section, recall_semantic_detail reference
  ```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_daemon/test_think_engine.py -v`
Expected: PASS (8 tests)

**Step 5: Commit**

```bash
git add src/everstaff/daemon/think_engine.py tests/test_daemon/test_think_engine.py
git commit -m "feat(daemon): replace ThinkEngine memory with DaemonStateStore + Mem0Client"
```

---

### Task 3: Update AgentLoop — replace memory with DaemonStateStore + Mem0Client

**Files:**
- Modify: `src/everstaff/daemon/agent_loop.py`
- Modify: `tests/test_daemon/test_agent_loop.py`

**Step 1: Update tests for new AgentLoop API**

Key changes to each test:
- Replace `memory=InMemoryStore()` with `daemon_state_store=DaemonStateStore(InMemoryFileStore())` + `agent_uuid="test-uuid"`
- Optionally add `mem0_client=FakeMem0()` where episode storage is tested
- Update assertions: `episode_query` → check `mem0.added`, `working_load` → `state_store.load`

Example for `test_loop_execute_cycle`:
```python
@pytest.mark.asyncio
async def test_loop_execute_cycle():
    bus = EventBus()
    bus.subscribe("test-agent")
    state_store = DaemonStateStore(InMemoryFileStore())
    mem0 = FakeMem0()

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
        mem0_client=mem0,
        tracer=NullTracer(),
        autonomy_level="autonomous",
        goals=[],
    )

    await bus.publish(AgentEvent(source="cron", type="cron.daily", target_agent="test-agent"))
    await loop.run_once()

    assert think.called
    assert runtime.called
    # Episode stored in mem0
    assert len(mem0.added) == 1
```

For `test_loop_updates_working_memory` → rename to `test_loop_updates_recent_decisions`:
```python
@pytest.mark.asyncio
async def test_loop_updates_recent_decisions():
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
        autonomy_level="autonomous",
        goals=[],
    )

    await bus.publish(AgentEvent(source="cron", type="tick", target_agent="test-agent"))
    await loop.run_once()

    state = await state_store.load("test-uuid")
    assert len(state.recent_decisions) > 0
    assert state.recent_decisions[-1]["action"] == "execute"
```

All 10 tests in the file need the same `memory=` → `daemon_state_store=` + `agent_uuid=` replacement.

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_daemon/test_agent_loop.py -v`
Expected: FAIL — AgentLoop constructor doesn't accept `daemon_state_store`

**Step 3: Implement AgentLoop changes**

Key changes to `src/everstaff/daemon/agent_loop.py`:

- Constructor (lines 53-71): Replace `memory: "MemoryStore"` with:
  ```python
  daemon_state_store: Any,      # DaemonStateStore
  agent_uuid: str,
  mem0_client: Any = None,      # Mem0Client | None
  ```
  Store as `self._state_store`, `self._agent_uuid`, `self._mem0`. Remove `self._memory`.

- Reflect phase (lines 242-267): Replace:
  ```python
  # Store episode in mem0
  if decision.action == "execute":
      episode_summary = (
          f"[{datetime.now(timezone.utc).isoformat()}] "
          f"Trigger: {event.source}:{event.type} | "
          f"Action: {decision.task_prompt} | "
          f"Result: {str(result)[:500]} | "
          f"Duration: {duration_ms}ms"
      )
      if self._mem0:
          await self._mem0.add(
              [{"role": "assistant", "content": episode_summary}],
              agent_id=self._agent_name,
              run_id=loop_session_id,
          )
      if self._internal_sensor is not None:
          self._internal_sensor.notify_episode()

  # Update structured state
  state = await self._state_store.load(self._agent_uuid)
  state.recent_decisions.append({
      "action": decision.action,
      "task": decision.task_prompt,
      "reasoning": decision.reasoning,
      "timestamp": datetime.now(timezone.utc).isoformat(),
  })
  state.recent_decisions = state.recent_decisions[-20:]
  await self._state_store.save(self._agent_uuid, state)
  ```

- Remove `from everstaff.protocols import Episode, WorkingState` usage in reflect (Episode is no longer needed as a protocol object; the summary goes directly to mem0).

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_daemon/test_agent_loop.py -v`
Expected: PASS (10 tests)

**Step 5: Commit**

```bash
git add src/everstaff/daemon/agent_loop.py tests/test_daemon/test_agent_loop.py
git commit -m "feat(daemon): replace AgentLoop memory with DaemonStateStore + Mem0Client"
```

---

### Task 4: Update AgentDaemon — accept and pass new stores

**Files:**
- Modify: `src/everstaff/daemon/agent_daemon.py`
- Modify: `tests/test_daemon/test_agent_daemon.py`

**Step 1: Update tests for new AgentDaemon API**

Replace all `memory=InMemoryStore()` with `daemon_state_store=DaemonStateStore(InMemoryFileStore())`.

Add FakeMem0 and InMemoryFileStore helpers (or import from a shared conftest).

Example for `_write_agent_yaml` helper — no changes needed (YAML doesn't include memory config).

Example for test constructor calls:
```python
daemon = AgentDaemon(
    agents_dir=agents_dir,
    daemon_state_store=DaemonStateStore(InMemoryFileStore()),
    tracer=NullTracer(),
    llm_factory=lambda **kw: None,
    runtime_factory=lambda **kw: None,
)
```

The `_SpyLoop` test (`test_daemon_passes_channel_registry_to_loop`) needs to accept new kwargs in AgentLoop.__init__. The spy captures kwargs, so as long as AgentLoop's constructor is updated (Task 3), this should work — just verify the kwargs contain `daemon_state_store` and `agent_uuid` instead of `memory`.

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_daemon/test_agent_daemon.py -v`
Expected: FAIL — AgentDaemon constructor doesn't accept `daemon_state_store`

**Step 3: Implement AgentDaemon changes**

Key changes to `src/everstaff/daemon/agent_daemon.py`:

- Constructor (lines 50-72): Replace `memory: "MemoryStore"` with:
  ```python
  daemon_state_store: Any,      # DaemonStateStore
  mem0_client: Any = None,      # Mem0Client | None
  ```
  Store as `self._state_store`, `self._mem0`. Remove `self._memory`.

- `_start_agent()` (lines 203-237):
  - ThinkEngine creation (line 205-211): Pass `daemon_state_store=self._state_store`, `agent_uuid=spec.uuid`, `mem0_client=self._mem0` instead of `memory=self._memory`.
  - AgentLoop creation (lines 220-237): Pass `daemon_state_store=self._state_store`, `agent_uuid=spec.uuid`, `mem0_client=self._mem0` instead of `memory=self._memory`.

- Remove `MemoryStore` from TYPE_CHECKING imports.

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_daemon/test_agent_daemon.py -v`
Expected: PASS (8 tests)

**Step 5: Commit**

```bash
git add src/everstaff/daemon/agent_daemon.py tests/test_daemon/test_agent_daemon.py
git commit -m "feat(daemon): replace AgentDaemon memory param with DaemonStateStore + Mem0Client"
```

---

### Task 5: Update learning cycle and integration tests

**Files:**
- Modify: `tests/test_daemon/test_learning_cycle.py`
- No changes needed: `tests/test_daemon/test_learning_integration.py` (tests InternalSensor and mutation_tools, not memory)
- No changes needed: `tests/test_daemon/test_goals.py` (pure model tests)

**Step 1: Update test_learning_cycle.py**

The tool schema tests need to check for `search_memory` instead of old tools:

```python
# tests/test_daemon/test_learning_cycle.py
"""Tests for the learning cycle -- insight recording via ThinkEngine."""
import pytest


def test_record_learning_insight_tool_exists():
    from everstaff.daemon.think_engine import THINK_TOOLS
    names = [t.name for t in THINK_TOOLS]
    assert "record_learning_insight" in names


def test_record_learning_insight_tool_schema():
    from everstaff.daemon.think_engine import THINK_TOOLS
    tool = next(t for t in THINK_TOOLS if t.name == "record_learning_insight")
    params = tool.parameters
    required = params.get("required", [])
    assert "category" in required
    assert "insight" in required
    assert "evidence" in required
    props = params["properties"]
    assert "category" in props
    assert "insight" in props
    assert "evidence" in props
    assert "action" in props


def test_search_memory_tool_exists():
    from everstaff.daemon.think_engine import THINK_TOOLS
    names = [t.name for t in THINK_TOOLS]
    assert "search_memory" in names


def test_old_recall_tools_removed():
    from everstaff.daemon.think_engine import THINK_TOOLS
    names = [t.name for t in THINK_TOOLS]
    assert "recall_semantic_detail" not in names
    assert "recall_recent_episodes" not in names
```

**Step 2: Run all daemon tests**

Run: `python -m pytest tests/test_daemon/ -v`
Expected: PASS (all tests)

**Step 3: Commit**

```bash
git add tests/test_daemon/test_learning_cycle.py
git commit -m "test(daemon): update learning cycle tests for mem0 migration"
```

---

### Task 6: Add shared test fixtures to conftest

**Files:**
- Create: `tests/test_daemon/conftest.py`

**Step 1: Extract common test helpers**

Move `InMemoryFileStore` and `FakeMem0` to conftest to avoid duplication:

```python
# tests/test_daemon/conftest.py
"""Shared fixtures for daemon tests."""
import pytest


class InMemoryFileStore:
    """Minimal FileStore implementation for testing."""
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
    """Minimal Mem0Client stand-in for testing."""
    def __init__(self):
        self.added: list[tuple] = []
        self.searched: list[str] = []

    async def add(self, messages, **scope):
        self.added.append((messages, scope))
        return []

    async def search(self, query, *, top_k=None, **scope):
        self.searched.append(query)
        return [{"memory": "relevant context", "score": 0.9}]
```

Then update `test_state_store.py`, `test_think_engine.py`, `test_agent_loop.py`, and `test_agent_daemon.py` to import from conftest:
```python
from tests.test_daemon.conftest import InMemoryFileStore, FakeMem0
```

Or use pytest fixtures:
```python
@pytest.fixture
def file_store():
    return InMemoryFileStore()

@pytest.fixture
def fake_mem0():
    return FakeMem0()
```

**Step 2: Run all tests**

Run: `python -m pytest tests/test_daemon/ -v`
Expected: PASS

**Step 3: Commit**

```bash
git add tests/test_daemon/conftest.py tests/test_daemon/test_state_store.py tests/test_daemon/test_think_engine.py tests/test_daemon/test_agent_loop.py tests/test_daemon/test_agent_daemon.py
git commit -m "refactor(test): extract shared daemon test fixtures to conftest"
```

---

### Task 7: Run full test suite and verify

**Step 1: Run all project tests**

Run: `python -m pytest tests/ -v --tb=short`
Expected: All tests pass. No regressions.

**Step 2: Check for any remaining references to old memory API in daemon code**

Run:
```bash
grep -rn "episode_append\|episode_query\|working_load\|working_save\|semantic_read\|semantic_write\|semantic_list\|recall_semantic_detail\|recall_recent_episodes" src/everstaff/daemon/
```
Expected: No matches.

**Step 3: Final commit if any fixes needed**

```bash
git add -A
git commit -m "chore(daemon): clean up remaining old memory references"
```

---

## Notes

- **Rebase**: The branch needs to be rebased onto local `main` (which has mem0 commits) before or after this implementation. The rebase was previously attempted but aborted due to 7-file conflicts. This plan can be implemented first, then rebased.
- **API wiring** (`src/everstaff/api/__init__.py`): The wiring changes described in the design doc should be done during the rebase resolution, since `api/__init__.py` is one of the conflicted files.
- **InMemoryStore**: After this migration, `InMemoryStore` (from `nulls.py`) is no longer used by daemon tests. It may still be used elsewhere in the project.

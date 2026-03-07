"""Tests for DaemonStateStore — structured daemon state persistence."""
import pytest
from everstaff.daemon.state_store import DaemonState, DaemonStateStore
from everstaff.daemon.goals import GoalBreakdown, SubGoal


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

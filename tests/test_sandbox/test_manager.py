"""Tests for ExecutorManager lifecycle."""
import pytest
from everstaff.sandbox.manager import ExecutorManager
from everstaff.sandbox.executor import SandboxExecutor
from everstaff.sandbox.models import SandboxCommand, SandboxResult, SandboxStatus
from everstaff.core.secret_store import SecretStore


class FakeExecutor(SandboxExecutor):
    """Concrete test executor."""
    def __init__(self):
        self._alive = False
        self._session_id = ""

    async def start(self, session_id: str) -> None:
        self._session_id = session_id
        self._alive = True

    async def execute(self, command):
        return SandboxResult(success=True, output="ok")

    async def stop(self) -> None:
        self._alive = False

    async def status(self):
        return SandboxStatus(alive=self._alive, session_id=self._session_id)

    @property
    def is_alive(self) -> bool:
        return self._alive


@pytest.mark.asyncio
class TestExecutorManager:
    async def test_get_or_create_creates_new(self):
        mgr = ExecutorManager(factory=lambda: FakeExecutor(), secret_store=SecretStore())
        executor = await mgr.get_or_create("session-1")
        assert executor.is_alive
        assert (await executor.status()).session_id == "session-1"

    async def test_get_or_create_returns_existing(self):
        mgr = ExecutorManager(factory=lambda: FakeExecutor(), secret_store=SecretStore())
        e1 = await mgr.get_or_create("session-1")
        e2 = await mgr.get_or_create("session-1")
        assert e1 is e2

    async def test_destroy_removes_executor(self):
        mgr = ExecutorManager(factory=lambda: FakeExecutor(), secret_store=SecretStore())
        executor = await mgr.get_or_create("session-1")
        await mgr.destroy("session-1")
        assert not executor.is_alive

    async def test_destroy_nonexistent_is_noop(self):
        mgr = ExecutorManager(factory=lambda: FakeExecutor(), secret_store=SecretStore())
        await mgr.destroy("nonexistent")  # should not raise

    async def test_list_active(self):
        mgr = ExecutorManager(factory=lambda: FakeExecutor(), secret_store=SecretStore())
        await mgr.get_or_create("s1")
        await mgr.get_or_create("s2")
        assert set(mgr.active_sessions) == {"s1", "s2"}

    async def test_destroy_all(self):
        mgr = ExecutorManager(factory=lambda: FakeExecutor(), secret_store=SecretStore())
        await mgr.get_or_create("s1")
        await mgr.get_or_create("s2")
        await mgr.destroy_all()
        assert len(mgr.active_sessions) == 0

    async def test_recreates_dead_executor(self):
        mgr = ExecutorManager(factory=lambda: FakeExecutor(), secret_store=SecretStore())
        e1 = await mgr.get_or_create("session-1")
        e1._alive = False  # Simulate executor death
        e2 = await mgr.get_or_create("session-1")
        assert e2.is_alive
        assert e1 is not e2  # New executor created

    async def test_has_active(self):
        """has_active returns True for running sessions."""
        mgr = ExecutorManager(factory=lambda: FakeExecutor(), secret_store=SecretStore())
        assert not mgr.has_active("s1")
        await mgr.get_or_create("s1")
        assert mgr.has_active("s1")
        await mgr.destroy("s1")
        assert not mgr.has_active("s1")

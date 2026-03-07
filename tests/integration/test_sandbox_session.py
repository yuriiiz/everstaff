import pytest
from pathlib import Path
from everstaff.sandbox.process_sandbox import ProcessSandbox
from everstaff.sandbox.manager import ExecutorManager
from everstaff.core.secret_store import SecretStore


@pytest.mark.asyncio
async def test_sandbox_session_end_to_end(tmp_path):
    """Full flow: ProcessSandbox start -> IPC server -> workspace -> stop."""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()

    secret_store = SecretStore({"OPENAI_API_KEY": "sk-test"})

    sandbox = ProcessSandbox(
        workdir=sessions_dir,
        secret_store=secret_store,
    )
    await sandbox.start("int-test-session")

    assert sandbox.is_alive
    assert sandbox._ipc_socket_path is not None
    assert Path(sandbox._ipc_socket_path).exists()

    # Verify per-session workspace created
    workspace = sessions_dir / "int-test-session" / "workspaces"
    assert workspace.exists()
    assert sandbox._workdir == workspace

    await sandbox.stop()
    assert not sandbox.is_alive


@pytest.mark.asyncio
async def test_executor_manager_lifecycle(tmp_path):
    """ExecutorManager creates and destroys executors."""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    secret_store = SecretStore()

    def factory():
        return ProcessSandbox(workdir=sessions_dir, secret_store=secret_store)

    mgr = ExecutorManager(factory=factory, secret_store=secret_store, idle_timeout=300)

    executor = await mgr.get_or_create("sid-1")
    assert executor.is_alive
    assert mgr.has_active("sid-1")

    await mgr.destroy("sid-1")
    assert not mgr.has_active("sid-1")


@pytest.mark.asyncio
async def test_executor_manager_destroy_all(tmp_path):
    """ExecutorManager.destroy_all stops all executors."""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    secret_store = SecretStore()

    def factory():
        return ProcessSandbox(workdir=sessions_dir, secret_store=secret_store)

    mgr = ExecutorManager(factory=factory, secret_store=secret_store)

    await mgr.get_or_create("sid-a")
    await mgr.get_or_create("sid-b")
    assert len(mgr.active_sessions) == 2

    await mgr.destroy_all()
    assert len(mgr.active_sessions) == 0

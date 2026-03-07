"""Tests for ProcessSandbox backend."""
import asyncio
import os
import sys
import pytest
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock
from everstaff.core.secret_store import SecretStore
from everstaff.sandbox.process_sandbox import ProcessSandbox
from everstaff.sandbox.models import SandboxCommand


@pytest.mark.asyncio
class TestProcessSandbox:
    async def test_start_and_stop(self, tmp_path):
        store = SecretStore({"KEY": "val"})
        sandbox = ProcessSandbox(workdir=tmp_path, secret_store=store)
        await sandbox.start("test-session")
        assert sandbox.is_alive
        await sandbox.stop()
        assert not sandbox.is_alive

    async def test_execute_bash_basic(self, tmp_path):
        store = SecretStore()
        sandbox = ProcessSandbox(workdir=tmp_path, secret_store=store)
        await sandbox.start("test-session")
        try:
            cmd = SandboxCommand(type="bash", payload={"command": "echo hello"})
            result = await sandbox.execute(cmd)
            assert result.success
            assert "hello" in result.output
        finally:
            await sandbox.stop()

    async def test_execute_bash_clean_env(self, tmp_path):
        """Bash commands in sandbox should NOT see parent os.environ."""
        os.environ["_SANDBOX_LEAK_TEST"] = "leaked"
        try:
            store = SecretStore({"_SANDBOX_LEAK_TEST": "leaked"})
            sandbox = ProcessSandbox(workdir=tmp_path, secret_store=store)
            await sandbox.start("test-session")
            cmd = SandboxCommand(type="bash", payload={"command": "echo $_SANDBOX_LEAK_TEST"})
            result = await sandbox.execute(cmd)
            assert "leaked" not in result.output
            await sandbox.stop()
        finally:
            os.environ.pop("_SANDBOX_LEAK_TEST", None)

    async def test_execute_bash_timeout(self, tmp_path):
        store = SecretStore()
        sandbox = ProcessSandbox(workdir=tmp_path, secret_store=store)
        await sandbox.start("test-session")
        try:
            cmd = SandboxCommand(type="bash", payload={"command": "sleep 60", "timeout": 2})
            result = await sandbox.execute(cmd)
            assert not result.success
            assert "timeout" in result.error.lower()
        finally:
            await sandbox.stop()

    async def test_execute_bash_exit_code(self, tmp_path):
        store = SecretStore()
        sandbox = ProcessSandbox(workdir=tmp_path, secret_store=store)
        await sandbox.start("test-session")
        try:
            cmd = SandboxCommand(type="bash", payload={"command": "exit 42"})
            result = await sandbox.execute(cmd)
            assert not result.success
            assert result.exit_code == 42
        finally:
            await sandbox.stop()

    async def test_execute_not_started(self, tmp_path):
        store = SecretStore()
        sandbox = ProcessSandbox(workdir=tmp_path, secret_store=store)
        cmd = SandboxCommand(type="bash", payload={"command": "echo test"})
        result = await sandbox.execute(cmd)
        assert not result.success
        assert "not running" in result.error.lower()

    async def test_execute_unknown_command_type(self, tmp_path):
        store = SecretStore()
        sandbox = ProcessSandbox(workdir=tmp_path, secret_store=store)
        await sandbox.start("test-session")
        try:
            cmd = SandboxCommand(type="unknown", payload={})
            result = await sandbox.execute(cmd)
            assert not result.success
            assert "unknown" in result.error.lower()
        finally:
            await sandbox.stop()

    async def test_status(self, tmp_path):
        store = SecretStore()
        sandbox = ProcessSandbox(workdir=tmp_path, secret_store=store)
        await sandbox.start("test-session")
        status = await sandbox.status()
        assert status.alive
        assert status.session_id == "test-session"
        assert status.uptime_seconds >= 0
        await sandbox.stop()

    async def test_status_after_stop(self, tmp_path):
        store = SecretStore()
        sandbox = ProcessSandbox(workdir=tmp_path, secret_store=store)
        await sandbox.start("test-session")
        await sandbox.stop()
        status = await sandbox.status()
        assert not status.alive

    async def test_execute_bash_timestamps(self, tmp_path):
        store = SecretStore()
        sandbox = ProcessSandbox(workdir=tmp_path, secret_store=store)
        await sandbox.start("test-session")
        try:
            cmd = SandboxCommand(type="bash", payload={"command": "echo hello"})
            result = await sandbox.execute(cmd)
            assert result.success
            assert result.started_at is not None
            assert result.finished_at is not None
            assert result.finished_at >= result.started_at
        finally:
            await sandbox.stop()


@pytest.mark.asyncio
class TestProcessSandboxSpawn:
    async def test_spawn_subprocess(self, tmp_path):
        """spawn_agent starts a subprocess with correct args."""
        sandbox = ProcessSandbox(workdir=tmp_path, secret_store=SecretStore({"KEY": "val"}))
        await sandbox.start("test-session")

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.pid = 12345
            mock_proc.returncode = None
            mock_exec.return_value = mock_proc

            await sandbox.spawn_agent(
                agent_spec_json='{"agent_name": "test"}',
                user_input="hello",
            )

            mock_exec.assert_called_once()
            args = mock_exec.call_args[0]
            assert sys.executable == args[0]
            assert "-m" in args
            assert "everstaff.sandbox.entry" in args
            assert "--socket-path" in args
            assert "--session-id" in args
            assert "--agent-spec" in args
            assert "--user-input" in args

        await sandbox.stop()

    async def test_spawn_agent_not_started(self, tmp_path):
        """spawn_agent raises if sandbox not started."""
        sandbox = ProcessSandbox(workdir=tmp_path, secret_store=SecretStore())
        with pytest.raises(RuntimeError, match="not started"):
            await sandbox.spawn_agent(agent_spec_json='{}')

    async def test_spawn_agent_already_spawned(self, tmp_path):
        """spawn_agent raises if already spawned."""
        sandbox = ProcessSandbox(workdir=tmp_path, secret_store=SecretStore())
        await sandbox.start("test-session")
        sandbox._process = MagicMock()  # simulate already spawned

        with pytest.raises(RuntimeError, match="already spawned"):
            await sandbox.spawn_agent(agent_spec_json='{}')

        sandbox._process = None  # clean up for stop
        await sandbox.stop()

    async def test_wait_finished(self, tmp_path):
        """wait_finished returns exit code."""
        sandbox = ProcessSandbox(workdir=tmp_path, secret_store=SecretStore())
        await sandbox.start("test-session")

        mock_proc = AsyncMock()
        mock_proc.wait = AsyncMock(return_value=0)
        mock_proc.returncode = 0
        sandbox._process = mock_proc

        code = await sandbox.wait_finished()
        assert code == 0

        sandbox._process = None  # clean up
        await sandbox.stop()

    async def test_wait_finished_no_process(self, tmp_path):
        """wait_finished returns -1 if no process."""
        sandbox = ProcessSandbox(workdir=tmp_path, secret_store=SecretStore())
        code = await sandbox.wait_finished()
        assert code == -1

    async def test_stop_terminates_subprocess(self, tmp_path):
        """stop() terminates running subprocess."""
        sandbox = ProcessSandbox(workdir=tmp_path, secret_store=SecretStore())
        await sandbox.start("test-session")

        mock_proc = AsyncMock()
        mock_proc.returncode = None
        mock_proc.wait = AsyncMock(return_value=0)
        sandbox._process = mock_proc

        await sandbox.stop()

        mock_proc.terminate.assert_called_once()
        assert sandbox._process is None


@pytest.mark.asyncio
async def test_stream_event_callback_wired(tmp_path):
    """ProcessSandbox forwards stream events to on_stream_event callback."""
    events = []
    async def on_stream(event_data):
        events.append(event_data)

    sandbox = ProcessSandbox(
        workdir=tmp_path, secret_store=SecretStore(),
        on_stream_event=on_stream,
    )
    await sandbox.start("test-session")

    result = await sandbox._ipc_handler.handle("stream.event", {
        "type": "text_delta", "content": "hello", "session_id": "test-session",
    })
    assert result == {}
    assert len(events) == 1
    assert events[0]["type"] == "text_delta"
    await sandbox.stop()


@pytest.mark.asyncio
async def test_workspace_dir_set_on_start(tmp_path):
    """start() creates workspace at sessions_dir/session_id/workspaces."""
    sandbox = ProcessSandbox(workdir=tmp_path, secret_store=SecretStore())
    await sandbox.start("sess-123")

    expected = tmp_path / "sess-123" / "workspaces"
    assert sandbox._workdir == expected
    assert expected.exists()
    await sandbox.stop()


@pytest.mark.asyncio
async def test_ipc_handler_has_memory_tracer_filestore(tmp_path):
    """ProcessSandbox IPC handler receives memory, tracer, file_store."""
    memory = AsyncMock()
    tracer = MagicMock()
    file_store = AsyncMock()

    sandbox = ProcessSandbox(
        workdir=tmp_path, secret_store=SecretStore(),
        memory_store=memory, tracer=tracer, file_store=file_store,
    )
    await sandbox.start("test-session")

    assert sandbox._ipc_handler._memory is memory
    assert sandbox._ipc_handler._tracer is tracer
    assert sandbox._ipc_handler._file_store is file_store
    await sandbox.stop()

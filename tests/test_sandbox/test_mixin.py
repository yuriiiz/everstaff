"""Tests for IpcSandboxMixin infrastructure."""
import asyncio
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from everstaff.core.secret_store import SecretStore
from everstaff.sandbox.mixin import IpcSandboxMixin
from everstaff.sandbox.executor import SandboxExecutor
from everstaff.sandbox.models import SandboxCommand, SandboxResult


class StubSandbox(IpcSandboxMixin, SandboxExecutor):
    """Minimal sandbox for testing mixin behavior."""
    def __init__(self):
        self._spawned = False
        self._killed = False
        self._spawn_args = None

    def _get_workdir(self, session_id: str) -> Path:
        import tempfile
        d = Path(tempfile.mkdtemp()) / session_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    async def _spawn(self, session_id, workdir, ipc_args, agent_spec_json="", user_input=None):
        self._spawned = True
        self._spawn_args = (session_id, workdir, ipc_args)

    async def _kill(self):
        self._killed = True

    async def execute(self, command):
        return SandboxResult(success=True)


@pytest.mark.asyncio
class TestIpcSandboxMixin:
    async def test_start_creates_ipc_and_calls_hooks(self):
        sandbox = StubSandbox()
        sandbox.configure_ipc(secret_store=SecretStore({"KEY": "val"}), config_data={"model_mappings": {}})
        await sandbox.start("test-session")
        assert sandbox.is_alive
        assert sandbox._ipc_server is not None
        assert sandbox._ipc_socket_path is not None
        await sandbox.stop()
        assert not sandbox.is_alive
        assert sandbox._killed

    async def test_stop_cleans_up_socket(self):
        sandbox = StubSandbox()
        sandbox.configure_ipc(secret_store=SecretStore())
        await sandbox.start("test-session")
        socket_path = sandbox._ipc_socket_path
        assert Path(socket_path).exists()
        await sandbox.stop()
        assert not Path(socket_path).exists()

    async def test_push_cancel_no_client(self):
        sandbox = StubSandbox()
        sandbox.configure_ipc(secret_store=SecretStore())
        await sandbox.start("test-session")
        await sandbox.push_cancel()  # should not raise
        await sandbox.stop()

    async def test_push_hitl_resolution_no_client(self):
        sandbox = StubSandbox()
        sandbox.configure_ipc(secret_store=SecretStore())
        await sandbox.start("test-session")
        await sandbox.push_hitl_resolution("hitl-1", "approved", "ok")
        await sandbox.stop()

    async def test_status(self):
        sandbox = StubSandbox()
        sandbox.configure_ipc(secret_store=SecretStore())
        await sandbox.start("test-session")
        status = await sandbox.status()
        assert status.alive
        assert status.session_id == "test-session"
        assert status.uptime_seconds >= 0
        await sandbox.stop()
        status = await sandbox.status()
        assert not status.alive

    async def test_on_file_change_default_noop(self):
        sandbox = StubSandbox()
        sandbox.configure_ipc(secret_store=SecretStore())
        await sandbox.start("test-session")
        await sandbox.on_file_change("test-session", ["/some/file.py"])
        await sandbox.stop()

    async def test_ipc_handler_receives_config_and_secrets(self):
        config_data = {"model_mappings": {"smart": {"model_id": "test-model"}}}
        sandbox = StubSandbox()
        sandbox.configure_ipc(secret_store=SecretStore({"API_KEY": "secret123"}), config_data=config_data)
        await sandbox.start("test-session")
        assert sandbox._ipc_handler._config_data == config_data
        assert sandbox._ipc_handler._secret_store.get("API_KEY") == "secret123"
        await sandbox.stop()

    async def test_spawn_agent_delegates(self):
        sandbox = StubSandbox()
        sandbox.configure_ipc(secret_store=SecretStore())
        await sandbox.start("test-session")
        await sandbox.spawn_agent(agent_spec_json='{"agent_name":"test"}', user_input="hello")
        assert sandbox._spawned
        await sandbox.stop()

    async def test_spawn_agent_not_started_raises(self):
        sandbox = StubSandbox()
        sandbox.configure_ipc(secret_store=SecretStore())
        with pytest.raises(RuntimeError, match="not started"):
            await sandbox.spawn_agent(agent_spec_json='{}')

    async def test_set_session_callbacks(self):
        sandbox = StubSandbox()
        sandbox.configure_ipc(secret_store=SecretStore())
        await sandbox.start("test-session")
        cb = AsyncMock()
        sandbox.set_session_callbacks(on_stream_event=cb)
        assert sandbox._on_stream_event is cb
        assert sandbox._ipc_handler._on_stream_event is cb
        await sandbox.stop()

    async def test_custom_create_ipc_server_hook(self):
        class CustomSandbox(StubSandbox):
            async def _create_ipc_server(self):
                self._custom_called = True
                await super()._create_ipc_server()

        sandbox = CustomSandbox()
        sandbox.configure_ipc(secret_store=SecretStore())
        await sandbox.start("test-session")
        assert sandbox._custom_called
        await sandbox.stop()

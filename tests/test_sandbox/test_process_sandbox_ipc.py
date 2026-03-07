"""Tests for ProcessSandbox with IPC integration."""
import asyncio
import pytest
from pathlib import Path

from everstaff.core.secret_store import SecretStore
from everstaff.sandbox.process_sandbox import ProcessSandbox


def _make_sandbox(tmp_path, secret_store=None):
    """Create a ProcessSandbox with IPC deps configured."""
    sandbox = ProcessSandbox(sessions_dir=tmp_path)
    sandbox.configure_ipc(secret_store=secret_store or SecretStore())
    return sandbox


@pytest.mark.asyncio
class TestProcessSandboxIpc:
    async def test_start_creates_ipc_server(self, tmp_path):
        """start() should create and start an IPC server."""
        sandbox = _make_sandbox(tmp_path, SecretStore({"API_KEY": "secret"}))
        await sandbox.start("test-session")
        try:
            assert sandbox.is_alive
            assert sandbox._ipc_socket_path is not None
            assert Path(sandbox._ipc_socket_path).parent.exists()
        finally:
            await sandbox.stop()

    async def test_stop_cleans_up_ipc(self, tmp_path):
        """stop() should close IPC server and remove socket file."""
        sandbox = _make_sandbox(tmp_path)
        await sandbox.start("test-session")
        socket_path = sandbox._ipc_socket_path
        await sandbox.stop()
        assert not sandbox.is_alive
        assert not Path(socket_path).exists()

    async def test_start_generates_ephemeral_token(self, tmp_path):
        """start() should generate an ephemeral token for sandbox auth."""
        sandbox = _make_sandbox(tmp_path, SecretStore({"KEY": "val"}))
        await sandbox.start("test-session")
        try:
            assert sandbox._ephemeral_token is not None
            assert len(sandbox._ephemeral_token) > 0
        finally:
            await sandbox.stop()

    async def test_push_cancel(self, tmp_path):
        """push_cancel() should send cancel message to sandbox via IPC."""
        sandbox = _make_sandbox(tmp_path)
        await sandbox.start("test-session")
        try:
            await sandbox.push_cancel()
        finally:
            await sandbox.stop()

    async def test_push_hitl_resolution(self, tmp_path):
        """push_hitl_resolution() should send resolution to sandbox via IPC."""
        sandbox = _make_sandbox(tmp_path)
        await sandbox.start("test-session")
        try:
            await sandbox.push_hitl_resolution(
                hitl_id="h1", decision="approved", comment="ok"
            )
        finally:
            await sandbox.stop()

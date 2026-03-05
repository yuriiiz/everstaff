"""Tests for ProcessSandbox with IPC integration."""
import asyncio
import pytest
from pathlib import Path

from everstaff.core.secret_store import SecretStore
from everstaff.sandbox.process_sandbox import ProcessSandbox


@pytest.mark.asyncio
class TestProcessSandboxIpc:
    async def test_start_creates_ipc_server(self, tmp_path):
        """start() should create and start an IPC server."""
        store = SecretStore({"API_KEY": "secret"})
        sandbox = ProcessSandbox(workdir=tmp_path, secret_store=store)
        await sandbox.start("test-session")
        try:
            assert sandbox.is_alive
            assert sandbox._ipc_socket_path is not None
            assert Path(sandbox._ipc_socket_path).parent.exists()
        finally:
            await sandbox.stop()

    async def test_stop_cleans_up_ipc(self, tmp_path):
        """stop() should close IPC server and remove socket file."""
        store = SecretStore()
        sandbox = ProcessSandbox(workdir=tmp_path, secret_store=store)
        await sandbox.start("test-session")
        socket_path = sandbox._ipc_socket_path
        await sandbox.stop()
        assert not sandbox.is_alive
        assert not Path(socket_path).exists()

    async def test_start_generates_ephemeral_token(self, tmp_path):
        """start() should generate an ephemeral token for sandbox auth."""
        store = SecretStore({"KEY": "val"})
        sandbox = ProcessSandbox(workdir=tmp_path, secret_store=store)
        await sandbox.start("test-session")
        try:
            assert sandbox._ephemeral_token is not None
            assert len(sandbox._ephemeral_token) > 0
        finally:
            await sandbox.stop()

    async def test_push_cancel(self, tmp_path):
        """push_cancel() should send cancel message to sandbox via IPC."""
        store = SecretStore()
        sandbox = ProcessSandbox(workdir=tmp_path, secret_store=store)
        await sandbox.start("test-session")
        try:
            # push_cancel should not raise even if no client connected
            await sandbox.push_cancel()
        finally:
            await sandbox.stop()

    async def test_push_hitl_resolution(self, tmp_path):
        """push_hitl_resolution() should send resolution to sandbox via IPC."""
        store = SecretStore()
        sandbox = ProcessSandbox(workdir=tmp_path, secret_store=store)
        await sandbox.start("test-session")
        try:
            await sandbox.push_hitl_resolution(
                hitl_id="h1", decision="approved", comment="ok"
            )
        finally:
            await sandbox.stop()

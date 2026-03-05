"""Tests for ProcessSandbox backend."""
import os
import pytest
from pathlib import Path
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

"""Tests for SandboxExecutor interface contracts."""
import pytest
from everstaff.sandbox.executor import SandboxExecutor
from everstaff.sandbox.models import SandboxCommand, SandboxResult, SandboxStatus


class TestSandboxModels:
    def test_sandbox_command_bash(self):
        cmd = SandboxCommand(type="bash", payload={"command": "ls", "timeout": 30})
        assert cmd.type == "bash"
        assert cmd.payload["command"] == "ls"

    def test_sandbox_result_success(self):
        result = SandboxResult(success=True, output="hello", exit_code=0)
        assert result.success is True
        assert result.output == "hello"

    def test_sandbox_result_failure(self):
        result = SandboxResult(success=False, error="timeout", exit_code=-1)
        assert result.success is False
        assert result.error == "timeout"

    def test_sandbox_status(self):
        status = SandboxStatus(alive=True, session_id="abc", uptime_seconds=10.0)
        assert status.alive is True
        assert status.session_id == "abc"


class TestSandboxExecutorIsAbstract:
    def test_cannot_instantiate(self):
        with pytest.raises(TypeError):
            SandboxExecutor()  # type: ignore

"""Tests for DockerSandbox backend."""
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from everstaff.core.secret_store import SecretStore
from everstaff.sandbox.docker_sandbox import DockerSandbox, DockerSandboxConfig
from everstaff.sandbox.models import SandboxCommand


def _make_docker_sandbox(tmp_path, secret_store=None, config=None):
    """Create a DockerSandbox with IPC deps configured."""
    sandbox = DockerSandbox(sessions_dir=tmp_path, config=config)
    sandbox.configure_ipc(secret_store=secret_store or SecretStore())
    return sandbox


class TestDockerSandboxConfig:
    def test_defaults(self):
        cfg = DockerSandboxConfig()
        assert cfg.image == "everstaff-sandbox:latest"
        assert cfg.memory_limit == "512m"
        assert cfg.cpu_limit == 1.0
        assert cfg.network_disabled is True

    def test_custom_values(self):
        cfg = DockerSandboxConfig(image="custom:v1", memory_limit="1g", cpu_limit=2.0)
        assert cfg.image == "custom:v1"
        assert cfg.memory_limit == "1g"


@pytest.mark.asyncio
class TestDockerSandbox:
    async def test_start_creates_ipc(self, tmp_path):
        """start() should create IPC server and be alive."""
        sandbox = _make_docker_sandbox(
            tmp_path,
            SecretStore({"API_KEY": "secret"}),
            DockerSandboxConfig(image="test-image:latest"),
        )
        await sandbox.start("test-session")
        assert sandbox.is_alive
        assert sandbox._ipc_socket_path is not None
        await sandbox.stop()

    async def test_spawn_creates_container(self, tmp_path):
        """_spawn() should create a Docker container with correct mounts."""
        sandbox = _make_docker_sandbox(
            tmp_path,
            SecretStore({"API_KEY": "secret"}),
            DockerSandboxConfig(image="test-image:latest"),
        )
        await sandbox.start("test-session")

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"container-id-123\n", b""))

        with patch("everstaff.sandbox.docker_sandbox.asyncio_create_subprocess_exec",
                    new_callable=AsyncMock, return_value=mock_proc):
            await sandbox.spawn_agent(agent_spec_json='{"agent_name":"test"}')
            assert sandbox._container_id == "container-id-123"

        # Clean up
        sandbox._container_id = None
        await sandbox.stop()

    async def test_stop_removes_container(self, tmp_path):
        """stop() should remove the Docker container."""
        sandbox = _make_docker_sandbox(tmp_path)
        sandbox._alive = True
        sandbox._container_id = "test-container"
        sandbox._session_id = "s1"

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))

        with patch("everstaff.sandbox.docker_sandbox.asyncio_create_subprocess_exec",
                    new_callable=AsyncMock, return_value=mock_proc) as mock_exec:
            await sandbox.stop()
            assert not sandbox.is_alive
            mock_exec.assert_awaited()
            call_args = mock_exec.call_args
            assert "rm" in call_args[0]

    async def test_push_cancel(self, tmp_path):
        """push_cancel() should send cancel to container via IPC."""
        sandbox = _make_docker_sandbox(tmp_path)
        sandbox._alive = True
        sandbox._client_writer = MagicMock()
        sandbox._client_writer.write = MagicMock()
        sandbox._client_writer.drain = AsyncMock()
        sandbox._session_id = "s1"

        await sandbox.push_cancel()
        sandbox._client_writer.write.assert_called_once()

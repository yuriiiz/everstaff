"""DockerSandbox -- Docker container-based sandbox backend."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from everstaff.sandbox.executor import SandboxExecutor
from everstaff.sandbox.mixin import IpcSandboxMixin
from everstaff.sandbox.models import SandboxCommand, SandboxResult

logger = logging.getLogger(__name__)


async def asyncio_create_subprocess_exec(*args, **kwargs):
    """Wrapper for testability."""
    return await asyncio.create_subprocess_exec(*args, **kwargs)


@dataclass
class DockerSandboxConfig:
    """Configuration for Docker sandbox containers."""
    image: str = "everstaff-sandbox:latest"
    memory_limit: str = "512m"
    cpu_limit: float = 1.0
    network_disabled: bool = True
    extra_mounts: dict[str, str] = field(default_factory=dict)


class DockerSandbox(IpcSandboxMixin, SandboxExecutor):
    """Sandbox that runs agent in a Docker container.

    Only handles container lifecycle. IPC infrastructure is in IpcSandboxMixin.
    """

    def __init__(
        self,
        sessions_dir: Path,
        config: DockerSandboxConfig | None = None,
    ) -> None:
        self._sessions_dir = sessions_dir
        self._docker_config = config or DockerSandboxConfig()
        self._container_id: str | None = None
        self._params_file: str | None = None

    def _get_workdir(self, session_id: str) -> Path:
        d = self._sessions_dir / session_id / "workspaces"
        d.mkdir(parents=True, exist_ok=True)
        return d

    async def _spawn(
        self,
        session_id: str,
        workdir: Path,
        ipc_args: dict[str, str],
        agent_spec_json: str = "",
        user_input: str | None = None,
    ) -> None:
        ipc_dir = str(Path(self._ipc_socket_path).parent)
        socket_filename = Path(self._ipc_socket_path).name

        # Write large payloads to temp file to avoid arg-length limits
        params = {"agent_spec": agent_spec_json or "{}"}
        if user_input is not None:
            params["user_input"] = user_input
        params_file = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", prefix="es-params-",
            dir=str(workdir), delete=False,
        )
        params_file.write(json.dumps(params))
        params_file.close()
        self._params_file = params_file.name
        params_filename = Path(self._params_file).name

        cmd = [
            "docker", "run", "-d",
            "--name", f"everstaff-{session_id}",
            "-v", f"{workdir}:/work",
            "-v", f"{ipc_dir}:/ipc",
            "-m", self._docker_config.memory_limit,
            f"--cpus={self._docker_config.cpu_limit}",
        ]
        if self._docker_config.network_disabled:
            cmd.append("--network=none")
        for host_path, container_path in self._docker_config.extra_mounts.items():
            cmd.extend(["-v", f"{host_path}:{container_path}"])
        cmd.extend([
            self._docker_config.image,
            "python", "-m", "everstaff.sandbox.entry",
            "--socket-path", f"/ipc/{socket_filename}",
            "--token", self._ephemeral_token,
            "--session-id", session_id,
            "--params-file", f"/work/{params_filename}",
            "--workspace-dir", "/work",
        ])

        process = await asyncio_create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            raise RuntimeError(f"Docker run failed: {stderr.decode()}")

        self._container_id = stdout.decode().strip()
        logger.info("DockerSandbox started container %s for session %s",
                     self._container_id, session_id)

    async def _kill(self) -> None:
        if self._container_id:
            try:
                proc = await asyncio_create_subprocess_exec(
                    "docker", "rm", "-f", self._container_id,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await proc.communicate()
            except Exception as e:
                logger.warning("Failed to remove container %s: %s", self._container_id, e)
            self._container_id = None
        if self._params_file:
            try:
                os.unlink(self._params_file)
            except OSError:
                pass
            self._params_file = None

    async def execute(self, command: SandboxCommand) -> SandboxResult:
        if not self._alive or not self._container_id:
            return SandboxResult(success=False, error="Sandbox not running")
        if command.type == "bash":
            return await self._exec_bash_docker(command.payload)
        return SandboxResult(success=False, error=f"Unknown command type: {command.type}")

    async def _exec_bash_docker(self, payload: dict) -> SandboxResult:
        cmd_str = payload.get("command", "")
        timeout = min(max(payload.get("timeout", 300), 1), 3600)
        started_at = time.monotonic()

        try:
            process = await asyncio_create_subprocess_exec(
                "docker", "exec", self._container_id, "sh", "-c", cmd_str,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=float(timeout)
                )
            except asyncio.TimeoutError:
                try:
                    process.terminate()
                    await process.wait()
                except Exception:
                    pass
                return SandboxResult(
                    success=False, exit_code=-1,
                    error=f"Timeout: command exceeded {timeout} seconds",
                    started_at=started_at, finished_at=time.monotonic(),
                )

            output = stdout.decode(errors="replace")
            err = stderr.decode(errors="replace")
            if err:
                output += f"\n{err}"

            return SandboxResult(
                success=process.returncode == 0,
                output=output.strip(),
                exit_code=process.returncode or 0,
                started_at=started_at, finished_at=time.monotonic(),
            )
        except Exception as e:
            return SandboxResult(
                success=False, error=str(e),
                started_at=started_at, finished_at=time.monotonic(),
            )

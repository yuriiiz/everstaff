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
from typing import Any, TYPE_CHECKING

from everstaff.sandbox.executor import SandboxExecutor
from everstaff.sandbox.ipc.server_handler import IpcServerHandler
from everstaff.sandbox.ipc.protocol import make_notification, parse_message, JsonRpcRequest, JsonRpcNotification, make_response
from everstaff.sandbox.token_store import EphemeralTokenStore
from everstaff.sandbox.models import SandboxCommand, SandboxResult, SandboxStatus

if TYPE_CHECKING:
    from everstaff.core.secret_store import SecretStore

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


class DockerSandbox(SandboxExecutor):
    """Sandbox that runs agent in a Docker container with IPC via bind-mounted socket.

    Lifecycle:
    1. start() -> create IPC socket on host, start IPC server, run container
       with bind mounts for workspace + IPC socket
    2. Container runs python -m everstaff.sandbox.entry
    3. Container connects to host IPC socket, authenticates, runs AgentRuntime
    4. stop() -> docker rm -f container, cleanup socket
    """

    def __init__(
        self,
        workdir: Path,
        secret_store: "SecretStore",
        config: DockerSandboxConfig | None = None,
    ) -> None:
        self._workdir = workdir
        self._secret_store = secret_store
        self._config = config or DockerSandboxConfig()
        self._session_id: str = ""
        self._alive: bool = False
        self._started_at: float = 0.0
        self._container_id: str | None = None

        # IPC state (same pattern as ProcessSandbox)
        self._ipc_socket_path: str | None = None
        self._ipc_server: asyncio.AbstractServer | None = None
        self._ipc_handler: IpcServerHandler | None = None
        self._ephemeral_token: str | None = None
        self._token_store: EphemeralTokenStore | None = None
        self._client_writer: asyncio.StreamWriter | None = None

    async def start(self, session_id: str) -> None:
        self._session_id = session_id
        self._workdir.mkdir(parents=True, exist_ok=True)

        # Create IPC socket on host
        tmpdir = tempfile.mkdtemp(prefix="everstaff-docker-ipc-")
        self._ipc_socket_path = os.path.join(tmpdir, f"{session_id}.sock")

        # Generate ephemeral token
        self._token_store = EphemeralTokenStore()
        self._ephemeral_token = self._token_store.create(session_id, ttl_seconds=60)

        # Start IPC server on host
        self._ipc_handler = IpcServerHandler(
            token_store=self._token_store,
            secret_store=self._secret_store,
        )
        self._ipc_server = await asyncio.start_unix_server(
            self._handle_connection,
            path=self._ipc_socket_path,
        )

        # Run Docker container
        ipc_dir = str(Path(self._ipc_socket_path).parent)
        cmd = [
            "docker", "run", "-d",
            "--name", f"everstaff-{session_id}",
            "-v", f"{self._workdir}:/work",
            "-v", f"{ipc_dir}:/ipc",
            "-m", self._config.memory_limit,
            f"--cpus={self._config.cpu_limit}",
        ]
        if self._config.network_disabled:
            cmd.append("--network=none")
        for host_path, container_path in self._config.extra_mounts.items():
            cmd.extend(["-v", f"{host_path}:{container_path}"])
        cmd.extend([
            self._config.image,
            "python", "-m", "everstaff.sandbox.entry",
            "--socket-path", f"/ipc/{session_id}.sock",
            "--token", self._ephemeral_token,
            "--session-id", session_id,
            "--agent-spec", "{}",
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
        self._alive = True
        self._started_at = time.monotonic()
        logger.info("DockerSandbox started container %s for session %s",
                     self._container_id, session_id)

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self._client_writer = writer
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                try:
                    msg = parse_message(line.decode().strip())
                    if isinstance(msg, (JsonRpcRequest, JsonRpcNotification)):
                        result = await self._ipc_handler.handle(msg.method, msg.params)
                        if msg.id is not None:
                            resp = make_response(result, msg.id)
                            writer.write(resp.model_dump_json().encode() + b"\n")
                            await writer.drain()
                except Exception:
                    logger.debug("Docker IPC message handling error", exc_info=True)
        except (asyncio.CancelledError, ConnectionError):
            pass
        except Exception as e:
            logger.debug("Docker IPC connection closed: %s", e)
        finally:
            self._client_writer = None
            writer.close()

    async def execute(self, command: SandboxCommand) -> SandboxResult:
        """Execute command inside Docker container via docker exec."""
        if not self._alive or not self._container_id:
            return SandboxResult(success=False, error="Sandbox not running")

        if command.type == "bash":
            return await self._exec_bash_docker(command.payload)
        return SandboxResult(success=False, error=f"Unknown command type: {command.type}")

    async def stop(self) -> None:
        # Stop and remove container
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

        # Close IPC server
        if self._ipc_server is not None:
            self._ipc_server.close()
            await self._ipc_server.wait_closed()
            self._ipc_server = None

        if self._client_writer is not None:
            self._client_writer.close()
            self._client_writer = None

        # Clean up socket
        if self._ipc_socket_path and Path(self._ipc_socket_path).exists():
            Path(self._ipc_socket_path).unlink(missing_ok=True)
            parent = Path(self._ipc_socket_path).parent
            try:
                parent.rmdir()
            except OSError:
                pass
            self._ipc_socket_path = None

        self._alive = False
        logger.info("DockerSandbox stopped for session %s", self._session_id)

    async def status(self) -> SandboxStatus:
        uptime = time.monotonic() - self._started_at if self._alive else 0.0
        return SandboxStatus(
            alive=self._alive,
            session_id=self._session_id,
            uptime_seconds=uptime,
        )

    @property
    def is_alive(self) -> bool:
        return self._alive

    async def push_cancel(self) -> None:
        await self._push_message("cancel", {"session_id": self._session_id})

    async def push_hitl_resolution(
        self, hitl_id: str, decision: str, comment: str = ""
    ) -> None:
        await self._push_message("hitl.resolution", {
            "hitl_id": hitl_id,
            "decision": decision,
            "comment": comment,
        })

    async def _push_message(self, method: str, params: dict) -> None:
        if self._client_writer is None:
            return
        try:
            msg = make_notification(method, params)
            self._client_writer.write(msg.model_dump_json().encode() + b"\n")
            await self._client_writer.drain()
        except Exception as e:
            logger.warning("Failed to push %s to docker sandbox: %s", method, e)

    async def _exec_bash_docker(self, payload: dict) -> SandboxResult:
        """Execute bash command inside Docker container."""
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

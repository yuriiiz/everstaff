"""ProcessSandbox -- local subprocess-based sandbox backend with IPC."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, TYPE_CHECKING

from everstaff.sandbox.executor import SandboxExecutor
from everstaff.sandbox.ipc.server_handler import IpcServerHandler
from everstaff.sandbox.ipc.protocol import make_notification
from everstaff.sandbox.token_store import EphemeralTokenStore
from everstaff.sandbox.models import SandboxCommand, SandboxResult, SandboxStatus

if TYPE_CHECKING:
    from everstaff.core.secret_store import SecretStore
    from everstaff.protocols import FileStore, MemoryStore, TracingBackend

logger = logging.getLogger(__name__)


def _minimal_env() -> dict[str, str]:
    """Minimal environment for subprocess execution.

    Only includes PATH, HOME, USER, LANG, TERM so basic commands work.
    Does NOT inherit parent process secrets or other environment variables.
    """
    env: dict[str, str] = {}
    for key in ("PATH", "HOME", "USER", "LANG", "TERM"):
        val = os.environ.get(key)
        if val is not None:
            env[key] = val
    return env


class ProcessSandbox(SandboxExecutor):
    """Sandbox that runs agent in a local subprocess with IPC channel.

    Lifecycle:
    1. start() -> creates IPC server + socket, generates ephemeral token
    2. Orchestrator spawns subprocess: python -m everstaff.sandbox.entry
    3. Subprocess connects, authenticates, receives secrets, runs AgentRuntime
    4. stop() -> closes IPC server, terminates process, cleans up socket
    """

    def __init__(
        self,
        workdir: Path,
        secret_store: "SecretStore",
        memory_store: "MemoryStore | None" = None,
        tracer: "TracingBackend | None" = None,
        file_store: "FileStore | None" = None,
        on_stream_event: Callable[..., Awaitable[None]] | None = None,
        on_hitl_detected: Callable[..., Awaitable[None]] | None = None,
    ) -> None:
        self._sessions_dir = workdir  # base sessions directory
        self._workdir = workdir       # will be updated in start()
        self._secret_store = secret_store
        self._memory_store = memory_store
        self._tracer = tracer
        self._file_store = file_store
        self._on_stream_event = on_stream_event
        self._on_hitl_detected = on_hitl_detected
        self._session_id: str = ""
        self._alive: bool = False
        self._started_at: float = 0.0
        self._subprocess_env = _minimal_env()

        # IPC state
        self._ipc_socket_path: str | None = None
        self._ipc_server: asyncio.AbstractServer | None = None
        self._ipc_handler: IpcServerHandler | None = None
        self._ephemeral_token: str | None = None
        self._token_store: EphemeralTokenStore | None = None
        self._client_writer: asyncio.StreamWriter | None = None
        self._process: asyncio.subprocess.Process | None = None

    # -- SandboxExecutor interface --

    async def start(self, session_id: str) -> None:
        self._session_id = session_id
        self._workdir = self._sessions_dir / session_id / "workspaces"
        self._workdir.mkdir(parents=True, exist_ok=True)

        # Create IPC socket in temp directory
        tmpdir = tempfile.mkdtemp(prefix="everstaff-ipc-")
        self._ipc_socket_path = os.path.join(tmpdir, f"{session_id}.sock")

        # Generate ephemeral token
        self._token_store = EphemeralTokenStore()
        self._ephemeral_token = self._token_store.create(session_id, ttl_seconds=30)

        # Start IPC server
        self._ipc_handler = IpcServerHandler(
            memory_store=self._memory_store,
            tracer=self._tracer,
            file_store=self._file_store,
            token_store=self._token_store,
            secret_store=self._secret_store,
            on_stream_event=self._on_stream_event,
            on_hitl_detected=self._on_hitl_detected,
        )
        self._ipc_server = await asyncio.start_unix_server(
            self._handle_connection,
            path=self._ipc_socket_path,
        )

        self._alive = True
        self._started_at = time.monotonic()
        logger.info("ProcessSandbox started for session %s at %s", session_id, self._workdir)

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Handle one sandbox subprocess IPC connection."""
        self._client_writer = writer
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                try:
                    from everstaff.sandbox.ipc.protocol import parse_message, JsonRpcRequest, JsonRpcNotification
                    msg = parse_message(line.decode().strip())
                    if isinstance(msg, (JsonRpcRequest, JsonRpcNotification)):
                        result = await self._ipc_handler.handle(msg.method, msg.params)
                        if msg.id is not None:
                            from everstaff.sandbox.ipc.protocol import make_response
                            resp = make_response(result, msg.id)
                            writer.write(resp.model_dump_json().encode() + b"\n")
                            await writer.drain()
                except Exception:
                    logger.debug("IPC message handling error", exc_info=True)
        except (asyncio.CancelledError, ConnectionError):
            pass
        except Exception as e:
            logger.debug("IPC connection closed: %s", e)
        finally:
            self._client_writer = None
            writer.close()

    async def spawn_agent(
        self,
        agent_spec_json: str,
        user_input: str | None = None,
    ) -> None:
        """Spawn the sandbox subprocess running the agent."""
        if not self._alive:
            raise RuntimeError("Sandbox not started")
        if self._process is not None:
            raise RuntimeError("Agent already spawned")

        cmd = [
            sys.executable, "-m", "everstaff.sandbox.entry",
            "--socket-path", self._ipc_socket_path,
            "--token", self._ephemeral_token,
            "--session-id", self._session_id,
            "--agent-spec", agent_spec_json,
            "--workspace-dir", str(self._workdir),
        ]
        if user_input is not None:
            cmd.extend(["--user-input", user_input])

        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            env=self._subprocess_env,
            cwd=self._workdir,
        )
        logger.info(
            "Spawned sandbox subprocess pid=%s for session %s",
            self._process.pid, self._session_id,
        )

    async def wait_finished(self, timeout: float | None = None) -> int:
        """Wait for the sandbox subprocess to exit. Returns exit code."""
        if self._process is None:
            return -1
        try:
            if timeout:
                await asyncio.wait_for(self._process.wait(), timeout)
            else:
                await self._process.wait()
        except asyncio.TimeoutError:
            self._process.terminate()
            await self._process.wait()
        return self._process.returncode or 0

    async def execute(self, command: SandboxCommand) -> SandboxResult:
        if not self._alive:
            return SandboxResult(success=False, error="Sandbox not running")
        if command.type == "bash":
            return await self._exec_bash(command.payload)
        return SandboxResult(success=False, error=f"Unknown command type: {command.type}")

    async def stop(self) -> None:
        # Terminate subprocess if running
        if self._process is not None:
            try:
                if self._process.returncode is None:
                    self._process.terminate()
                    await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None

        # Close IPC server
        if self._ipc_server is not None:
            self._ipc_server.close()
            await self._ipc_server.wait_closed()
            self._ipc_server = None

        # Close client connection
        if self._client_writer is not None:
            self._client_writer.close()
            self._client_writer = None

        # Clean up socket file
        if self._ipc_socket_path and Path(self._ipc_socket_path).exists():
            Path(self._ipc_socket_path).unlink(missing_ok=True)
            parent = Path(self._ipc_socket_path).parent
            try:
                parent.rmdir()
            except OSError:
                pass
            self._ipc_socket_path = None

        self._alive = False
        logger.info("ProcessSandbox stopped for session %s", self._session_id)

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
        """Push cancel signal to sandbox via IPC."""
        await self._push_message("cancel", {"session_id": self._session_id})

    async def push_hitl_resolution(
        self, hitl_id: str, decision: str, comment: str = ""
    ) -> None:
        """Push HITL resolution to sandbox via IPC."""
        await self._push_message("hitl.resolution", {
            "hitl_id": hitl_id,
            "decision": decision,
            "comment": comment,
        })

    # -- internal helpers --

    async def _push_message(self, method: str, params: dict) -> None:
        """Send a server-push message to connected sandbox client."""
        if self._client_writer is None:
            logger.debug("No sandbox client connected, cannot push %s", method)
            return
        try:
            msg = make_notification(method, params)
            self._client_writer.write(msg.model_dump_json().encode() + b"\n")
            await self._client_writer.drain()
        except Exception as e:
            logger.warning("Failed to push %s to sandbox: %s", method, e)

    async def _exec_bash(self, payload: dict) -> SandboxResult:
        cmd = payload.get("command", "")
        timeout = min(max(payload.get("timeout", 300), 1), 3600)
        started_at = time.monotonic()

        try:
            process = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._workdir,
                env=self._subprocess_env,
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
                    success=False,
                    exit_code=-1,
                    error=f"Timeout: command exceeded {timeout} seconds",
                    started_at=started_at,
                    finished_at=time.monotonic(),
                )

            output = stdout.decode(errors="replace")
            err = stderr.decode(errors="replace")
            if err:
                output += f"\n{err}"

            return SandboxResult(
                success=process.returncode == 0,
                output=output.strip(),
                exit_code=process.returncode or 0,
                started_at=started_at,
                finished_at=time.monotonic(),
            )
        except Exception as e:
            return SandboxResult(
                success=False,
                error=str(e),
                started_at=started_at,
                finished_at=time.monotonic(),
            )

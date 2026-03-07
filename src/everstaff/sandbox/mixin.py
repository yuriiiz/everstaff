"""IpcSandboxMixin — shared IPC infrastructure for sandbox backends."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, TYPE_CHECKING

from everstaff.sandbox.ipc.protocol import (
    make_notification,
    make_response,
    parse_message,
    JsonRpcRequest,
    JsonRpcNotification,
)
from everstaff.sandbox.ipc.server_handler import IpcServerHandler
from everstaff.sandbox.models import SandboxStatus
from everstaff.sandbox.token_store import EphemeralTokenStore

if TYPE_CHECKING:
    from everstaff.core.secret_store import SecretStore
    from everstaff.protocols import FileStore, MemoryStore, TracingBackend

logger = logging.getLogger(__name__)


class IpcSandboxMixin:
    """Shared IPC infrastructure for sandbox backends.

    Handles: IPC server lifecycle, auth + config + secret injection,
    ephemeral tokens, connection management, event routing, push messages.

    Subclasses implement only:
      _spawn(session_id, workdir, ipc_args, agent_spec_json, user_input) — start the process/container
      _kill() — stop the process/container
      _get_workdir(session_id) -> Path — return workspace path

    Optional overrides:
      _create_ipc_server() — default: Unix socket; override for TCP, etc.
      _ipc_connect_args() -> dict — connection params passed to subprocess
      on_file_change(session_id, changed_paths) — default: no-op
    """

    def configure_ipc(
        self,
        secret_store: "SecretStore | None" = None,
        memory_store: "MemoryStore | None" = None,
        tracer: "TracingBackend | None" = None,
        file_store: "FileStore | None" = None,
        config_data: dict[str, Any] | None = None,
        on_stream_event: Callable[..., Awaitable[None]] | None = None,
        on_hitl_detected: Callable[..., Awaitable[None]] | None = None,
        mem0_client: Any | None = None,
    ) -> None:
        """Inject IPC dependencies. Called by ExecutorManager, not by sandbox implementers."""
        self._secret_store = secret_store
        self._memory_store = memory_store
        self._tracer = tracer
        self._file_store = file_store
        self._config_data = config_data or {}
        self._on_stream_event = on_stream_event
        self._on_hitl_detected = on_hitl_detected
        self._mem0_client = mem0_client
        self._session_id: str = ""
        self._alive: bool = False
        self._started_at: float = 0.0
        self._ipc_socket_path: str | None = None
        self._ipc_server: asyncio.AbstractServer | None = None
        self._ipc_handler: IpcServerHandler | None = None
        self._ephemeral_token: str | None = None
        self._token_store: EphemeralTokenStore | None = None
        self._client_writer: asyncio.StreamWriter | None = None
        self._connection_done: asyncio.Event = asyncio.Event()

    def set_session_callbacks(
        self,
        on_stream_event: Callable[..., Awaitable[None]] | None = None,
        tracer: "TracingBackend | None" = None,
    ) -> None:
        """Update per-session callbacks. Called before spawn_agent."""
        if on_stream_event is not None:
            self._on_stream_event = on_stream_event
            if self._ipc_handler:
                self._ipc_handler._on_stream_event = on_stream_event
        if tracer is not None:
            self._tracer = tracer
            if self._ipc_handler:
                self._ipc_handler._tracer = tracer

    # -- SandboxExecutor interface (implemented by mixin) --

    async def start(self, session_id: str) -> None:
        self._session_id = session_id
        workdir = self._get_workdir(session_id)
        workdir.mkdir(parents=True, exist_ok=True)
        await self._start_ipc(session_id)
        self._alive = True
        self._started_at = time.monotonic()
        logger.info("sandbox started session=%s workdir=%s", session_id, workdir)

    async def stop(self) -> None:
        await self._kill()
        await self._stop_ipc()
        self._alive = False
        logger.info("sandbox stopped session=%s", self._session_id)

    async def status(self) -> SandboxStatus:
        uptime = time.monotonic() - self._started_at if self._alive else 0.0
        return SandboxStatus(alive=self._alive, session_id=self._session_id, uptime_seconds=uptime)

    @property
    def is_alive(self) -> bool:
        return self._alive

    async def push_cancel(self) -> None:
        await self._push_message("cancel", {"session_id": self._session_id})

    async def push_hitl_resolution(self, hitl_id: str, decision: str, comment: str = "") -> None:
        await self._push_message("hitl.resolution", {"hitl_id": hitl_id, "decision": decision, "comment": comment})

    async def on_file_change(self, session_id: str, changed_paths: list[str]) -> None:
        """File change callback. Default no-op. Override for remote sync."""

    async def spawn_agent(self, agent_spec_json: str, user_input: str | None = None) -> None:
        if not self._alive:
            raise RuntimeError("Sandbox not started")
        # Generate a fresh single-use token for each spawn
        self._ephemeral_token = self._token_store.create(self._session_id, ttl_seconds=30)
        workdir = self._get_workdir(self._session_id)
        await self._spawn(
            session_id=self._session_id, workdir=workdir, ipc_args=self._ipc_connect_args(),
            agent_spec_json=agent_spec_json, user_input=user_input,
        )

    async def wait_finished(self, timeout: float | None = None) -> int:
        return 0

    # -- IPC infrastructure (private) --

    async def _start_ipc(self, session_id: str) -> None:
        self._token_store = EphemeralTokenStore()
        self._ephemeral_token = self._token_store.create(session_id, ttl_seconds=30)
        self._ipc_handler = IpcServerHandler(
            memory_store=self._memory_store, tracer=self._tracer, file_store=self._file_store,
            token_store=self._token_store, secret_store=self._secret_store,
            on_stream_event=self._on_stream_event, on_hitl_detected=self._on_hitl_detected,
            config_data=self._config_data,
            mem0_client=self._mem0_client,
        )
        await self._create_ipc_server()

    async def _stop_ipc(self) -> None:
        if self._ipc_server is not None:
            self._ipc_server.close()
            await self._ipc_server.wait_closed()
            self._ipc_server = None
        if self._client_writer is not None:
            self._client_writer.close()
            self._client_writer = None
        if self._ipc_socket_path and Path(self._ipc_socket_path).exists():
            Path(self._ipc_socket_path).unlink(missing_ok=True)
            parent = Path(self._ipc_socket_path).parent
            try:
                parent.rmdir()
            except OSError:
                pass
            self._ipc_socket_path = None

    async def _create_ipc_server(self) -> None:
        """Create IPC server. Default: Unix socket. Override for TCP, etc."""
        short_id = hashlib.sha256(self._session_id.encode()).hexdigest()[:8]
        tmpdir = tempfile.mkdtemp(prefix="es-", dir="/tmp")
        self._ipc_socket_path = os.path.join(tmpdir, f"{short_id}.sock")
        self._ipc_server = await asyncio.start_unix_server(self._handle_connection, path=self._ipc_socket_path)

    def _ipc_connect_args(self) -> dict[str, str]:
        return {"socket_path": self._ipc_socket_path}

    def _ipc_cli_args(self, connect_args: dict[str, str]) -> list[str]:
        args = []
        if "socket_path" in connect_args:
            args.extend(["--socket-path", connect_args["socket_path"]])
        if not self._ephemeral_token:
            raise RuntimeError("No ephemeral token available — was start() called?")
        args.extend(["--token", self._ephemeral_token])
        return args

    async def wait_drained(self, timeout: float = 5.0) -> None:
        """Wait for the IPC connection handler to finish processing all messages."""
        try:
            await asyncio.wait_for(self._connection_done.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.debug("wait_drained timed out timeout=%.1fs session=%s", timeout, self._session_id)

    async def _handle_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._connection_done.clear()
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
                    logger.debug("IPC message handling error", exc_info=True)
        except (asyncio.CancelledError, ConnectionError):
            pass
        except Exception as e:
            logger.debug("IPC connection closed error=%s", e)
        finally:
            self._client_writer = None
            writer.close()
            self._connection_done.set()

    async def _push_message(self, method: str, params: dict) -> None:
        if self._client_writer is None:
            logger.debug("no sandbox client connected, cannot push method=%s", method)
            return
        try:
            msg = make_notification(method, params)
            self._client_writer.write(msg.model_dump_json().encode() + b"\n")
            await self._client_writer.drain()
        except Exception as e:
            logger.warning("failed to push to sandbox method=%s error=%s", method, e)

    # -- Hooks for subclasses --

    def _get_workdir(self, session_id: str) -> Path:
        raise NotImplementedError

    async def _spawn(self, session_id: str, workdir: Path, ipc_args: dict[str, str],
                     agent_spec_json: str = "", user_input: str | None = None) -> None:
        raise NotImplementedError

    async def _kill(self) -> None:
        raise NotImplementedError

"""ProcessSandbox -- local subprocess-based sandbox backend."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import tempfile
from pathlib import Path
from everstaff.sandbox.executor import SandboxExecutor
from everstaff.sandbox.mixin import IpcSandboxMixin
from everstaff.sandbox.models import SandboxCommand, SandboxResult

logger = logging.getLogger(__name__)


def _minimal_env() -> dict[str, str]:
    """Minimal environment for subprocess execution."""
    env: dict[str, str] = {}
    for key in ("PATH", "HOME", "USER", "LANG", "TERM", "LOG_LEVEL"):
        val = os.environ.get(key)
        if val is not None:
            env[key] = val
    return env


class ProcessSandbox(IpcSandboxMixin, SandboxExecutor):
    """Sandbox that runs agent in a local subprocess.

    Only handles process lifecycle. IPC infrastructure is in IpcSandboxMixin.
    """

    def __init__(self, sessions_dir: Path) -> None:
        self._sessions_dir = sessions_dir
        self._process: asyncio.subprocess.Process | None = None
        self._subprocess_env = _minimal_env()
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
        if self._process is not None:
            raise RuntimeError("Agent already spawned")

        # Write large payloads to temp files to avoid OS arg-length limits
        params = {"agent_spec": agent_spec_json or "{}"}
        if user_input is not None:
            params["user_input"] = user_input
        params_file = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", prefix="es-params-",
            dir="/tmp", delete=False,
        )
        params_file.write(json.dumps(params))
        params_file.close()
        self._params_file = params_file.name

        cmd = [
            sys.executable, "-m", "everstaff.sandbox.entry",
            "--session-id", session_id,
            "--workspace-dir", str(workdir),
            *self._ipc_cli_args(ipc_args),
            "--params-file", self._params_file,
        ]

        logger.info("sandbox spawn session=%s ipc_args=%s token_len=%s cmd_len=%d",
                    session_id, ipc_args, len(self._ephemeral_token) if self._ephemeral_token else 0, len(cmd))
        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            env=self._subprocess_env,
            cwd=workdir,
        )
        logger.info(
            "Spawned sandbox subprocess pid=%s for session %s",
            self._process.pid, session_id,
        )

    async def _kill(self) -> None:
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
        if self._params_file:
            try:
                os.unlink(self._params_file)
            except OSError:
                pass
            self._params_file = None

    async def wait_finished(self, timeout: float | None = None) -> int:
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
        rc = self._process.returncode or 0
        self._process = None  # allow re-spawn
        return rc

    async def execute(self, command: SandboxCommand) -> SandboxResult:
        if not self._alive:
            return SandboxResult(success=False, error="Sandbox not running")
        if command.type == "bash":
            return await self._exec_bash(command.payload)
        return SandboxResult(success=False, error=f"Unknown command type: {command.type}")

    async def _exec_bash(self, payload: dict) -> SandboxResult:
        import time as _time
        cmd = payload.get("command", "")
        timeout = min(max(payload.get("timeout", 300), 1), 3600)
        started_at = _time.monotonic()
        workdir = self._get_workdir(self._session_id)

        try:
            process = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=workdir,
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
                    success=False, exit_code=-1,
                    error=f"Timeout: command exceeded {timeout} seconds",
                    started_at=started_at, finished_at=_time.monotonic(),
                )

            output = stdout.decode(errors="replace")
            err = stderr.decode(errors="replace")
            if err:
                output += f"\n{err}"

            return SandboxResult(
                success=process.returncode == 0,
                output=output.strip(),
                exit_code=process.returncode or 0,
                started_at=started_at, finished_at=_time.monotonic(),
            )
        except Exception as e:
            return SandboxResult(
                success=False, error=str(e),
                started_at=started_at, finished_at=_time.monotonic(),
            )

"""ProcessSandbox -- local subprocess-based sandbox backend."""
from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING

from everstaff.sandbox.executor import SandboxExecutor
from everstaff.sandbox.models import SandboxCommand, SandboxResult, SandboxStatus

if TYPE_CHECKING:
    from everstaff.core.secret_store import SecretStore

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
    """Sandbox that runs commands as local subprocesses with clean env.

    Secrets from SecretStore are NOT exposed to subprocesses.
    Subprocesses get only a minimal environment (PATH, HOME, etc.).
    """

    def __init__(self, workdir: Path, secret_store: "SecretStore") -> None:
        self._workdir = workdir
        self._secret_store = secret_store
        self._session_id: str = ""
        self._alive: bool = False
        self._started_at: float = 0.0
        self._subprocess_env = _minimal_env()

    # -- SandboxExecutor interface --

    async def start(self, session_id: str) -> None:
        self._session_id = session_id
        self._alive = True
        self._started_at = time.monotonic()
        self._workdir.mkdir(parents=True, exist_ok=True)
        logger.info("ProcessSandbox started for session %s at %s", session_id, self._workdir)

    async def execute(self, command: SandboxCommand) -> SandboxResult:
        if not self._alive:
            return SandboxResult(success=False, error="Sandbox not running")

        if command.type == "bash":
            return await self._exec_bash(command.payload)
        return SandboxResult(success=False, error=f"Unknown command type: {command.type}")

    async def stop(self) -> None:
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

    # -- internal helpers --

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

"""Bash — execute shell commands within the agent's workspace."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from everstaff.tools.native import tool

logger = logging.getLogger(__name__)


def _bash_permission_hint(args):
    from everstaff.protocols import PermissionHint
    cmd = args.get("command", "").strip()
    if not cmd:
        return PermissionHint("command", "*")
    prefix = cmd.split()[0]
    return PermissionHint("command", f"{prefix} *")


def make_bash_tool(workdir: Path):
    """Return a Bash NativeTool scoped to *workdir*."""

    @tool(name="Bash", description="Execute a shell command and return stdout + stderr.",
          permission_hint=_bash_permission_hint)
    async def bash(command: str, timeout: int = 300) -> str:
        """Execute a terminal command and return the combined output."""
        timeout = min(max(timeout, 10), 3600)  # clamp: 10s–3600s
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=workdir,
            )
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=float(timeout))
            except asyncio.TimeoutError:
                try:
                    process.terminate()
                    await process.wait()
                except Exception:
                    pass
                logger.warning("Bash command timed out after %ds: %.200s", timeout, command)
                return f"Error: Command timed out after {timeout} seconds."

            output = stdout.decode(errors="replace")
            err = stderr.decode(errors="replace")

            if err:
                output += f"\nSTDERR:\n{err}"

            return output.strip() if output.strip() else "(Command executed with no output)"

        except Exception as e:
            logger.error("Bash command failed: %s — %s", command[:200], e)
            return f"Error: {e}"

    return bash


TOOLS = [make_bash_tool(Path("."))]
TOOLS_FACTORY = make_bash_tool

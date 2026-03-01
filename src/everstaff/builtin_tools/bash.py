"""Bash — execute shell commands within the agent's workspace."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from everstaff.tools.native import tool

logger = logging.getLogger(__name__)


def make_bash_tool(workdir: Path):
    """Return a Bash NativeTool scoped to *workdir*."""

    @tool(name="Bash", description="Execute a shell command and return stdout + stderr.")
    async def bash(command: str) -> str:
        """Execute a terminal command and return the combined output."""
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=workdir,
            )
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=300.0)
            except asyncio.TimeoutError:
                try:
                    process.terminate()
                    await process.wait()
                except Exception:
                    pass
                logger.warning("Bash command timed out after 300s: %.200s", command)
                return "Error: Command timed out after 300 seconds."

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

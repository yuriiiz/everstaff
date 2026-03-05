"""Data models for sandbox communication."""
from __future__ import annotations

from pydantic import BaseModel


class SandboxCommand(BaseModel):
    """Command sent to a sandbox executor."""
    type: str  # "bash", "mcp_start", "file_read", "file_write", etc.
    payload: dict


class SandboxResult(BaseModel):
    """Result returned from sandbox command execution."""
    success: bool
    output: str = ""
    exit_code: int = 0
    error: str = ""


class SandboxStatus(BaseModel):
    """Current status of a sandbox executor."""
    alive: bool
    session_id: str
    uptime_seconds: float = 0.0

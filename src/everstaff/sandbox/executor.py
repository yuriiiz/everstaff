"""Abstract base class for sandbox executors."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from everstaff.sandbox.models import SandboxCommand, SandboxResult, SandboxStatus


class SandboxExecutor(ABC):
    """Abstract sandbox executor.

    Each session gets one executor. The executor manages an isolated
    environment where agent tools run.
    """

    @abstractmethod
    async def start(self, session_id: str) -> None:
        """Start the sandbox and complete secret injection."""

    @abstractmethod
    async def execute(self, command: "SandboxCommand") -> "SandboxResult":
        """Execute a command inside the sandbox."""

    @abstractmethod
    async def stop(self) -> None:
        """Destroy the sandbox and clean up resources."""

    @abstractmethod
    async def status(self) -> "SandboxStatus":
        """Return current sandbox status."""

    @property
    @abstractmethod
    def is_alive(self) -> bool:
        """Whether the sandbox is running."""

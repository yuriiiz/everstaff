"""Abstract IPC channel for sandbox communication."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable, Awaitable


class IpcChannel(ABC):
    """Abstract bidirectional IPC channel.

    Client side connects to server; supports request/response and
    fire-and-forget notifications. Server can push messages to client.
    """

    @abstractmethod
    async def connect(self, address: str) -> None:
        """Connect to the IPC server."""

    @abstractmethod
    async def send_request(self, method: str, params: dict[str, Any]) -> Any:
        """Send request and wait for response. Returns result dict."""

    @abstractmethod
    async def send_notification(self, method: str, params: dict[str, Any]) -> None:
        """Fire-and-forget notification (no response expected)."""

    @abstractmethod
    def on_push(self, method: str, handler: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
        """Register handler for server-pushed messages."""

    @abstractmethod
    async def close(self) -> None:
        """Close the connection."""

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Whether the channel is connected."""

"""Sensor ABC — formal interface for all daemon sensors."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from everstaff.daemon.event_bus import EventBus


class Sensor(ABC):
    """Base class for all sensors that feed events into the daemon EventBus."""

    @abstractmethod
    async def start(self, event_bus: "EventBus") -> None:
        """Start producing events and publishing them to *event_bus*."""

    @abstractmethod
    async def stop(self) -> None:
        """Stop producing events and release resources."""

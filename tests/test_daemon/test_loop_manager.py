"""Tests for LoopManager — lifecycle management of AgentLoop instances."""
from __future__ import annotations

import asyncio

import pytest

from everstaff.daemon.loop_manager import LoopManager


class FakeLoop:
    def __init__(self, name: str):
        self._agent_name = name
        self._running = False
        self.stopped = False

    @property
    def agent_name(self) -> str:
        return self._agent_name

    @property
    def is_running(self) -> bool:
        return self._running

    async def run(self):
        self._running = True
        try:
            while self._running:
                await asyncio.sleep(0.05)
        finally:
            self._running = False

    def stop(self):
        self._running = False
        self.stopped = True


@pytest.mark.asyncio
async def test_start_creates_task():
    mgr = LoopManager()
    loop = FakeLoop("agent-a")
    await mgr.start(loop)
    assert mgr.has("agent-a")
    await mgr.stop("agent-a")


@pytest.mark.asyncio
async def test_stop_cancels_task():
    mgr = LoopManager()
    loop = FakeLoop("agent-a")
    await mgr.start(loop)
    await mgr.stop("agent-a")
    assert not mgr.has("agent-a")
    assert loop.stopped


@pytest.mark.asyncio
async def test_get_status():
    mgr = LoopManager()
    loop1 = FakeLoop("agent-a")
    loop2 = FakeLoop("agent-b")
    await mgr.start(loop1)
    await mgr.start(loop2)
    status = mgr.get_status()
    assert "agent-a" in status
    assert "agent-b" in status
    await mgr.stop_all()


@pytest.mark.asyncio
async def test_stop_all():
    mgr = LoopManager()
    loop1 = FakeLoop("agent-a")
    loop2 = FakeLoop("agent-b")
    await mgr.start(loop1)
    await mgr.start(loop2)
    await mgr.stop_all()
    assert not mgr.has("agent-a")
    assert not mgr.has("agent-b")


@pytest.mark.asyncio
async def test_has_agent():
    mgr = LoopManager()
    assert not mgr.has("nonexistent")
    loop = FakeLoop("agent-a")
    await mgr.start(loop)
    assert mgr.has("agent-a")
    await mgr.stop_all()

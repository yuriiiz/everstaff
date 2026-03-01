"""Integration tests for AgentDaemon wired into the FastAPI app lifecycle."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_daemon_starts_and_stops(tmp_path):
    """AgentDaemon can be created, started, and stopped with minimal config."""
    from everstaff.daemon.agent_daemon import AgentDaemon
    from everstaff.nulls import InMemoryStore, NullTracer

    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()

    daemon = AgentDaemon(
        agents_dir=agents_dir,
        memory=InMemoryStore(),
        tracer=NullTracer(),
        llm_factory=lambda **kw: None,
        runtime_factory=lambda **kw: None,
    )
    await daemon.start()
    assert daemon.is_running
    await daemon.stop()
    assert not daemon.is_running


@pytest.mark.asyncio
async def test_daemon_disabled_by_default():
    """DaemonConfig.enabled defaults to False."""
    from everstaff.core.config import DaemonConfig

    cfg = DaemonConfig()
    assert cfg.enabled is False


@pytest.mark.asyncio
async def test_build_memory_store(tmp_path):
    """build_memory_store creates a FileMemoryStore with dual FileStore."""
    from everstaff.core.config import StorageConfig
    from everstaff.core.factories import build_memory_store
    from everstaff.memory.file_store import FileMemoryStore

    sessions = str(tmp_path / "sessions")
    memory = str(tmp_path / "memory")

    store = build_memory_store(StorageConfig(), sessions, memory)
    assert isinstance(store, FileMemoryStore)
    # Verify dual stores are wired
    assert store._session_store is not None
    assert store._memory_store is not None

"""Tests for AgentDaemon — top-level orchestrator for autonomous agent loops."""
import asyncio
import pytest
from pathlib import Path

from everstaff.daemon.agent_daemon import AgentDaemon
from everstaff.daemon.event_bus import EventBus
from everstaff.daemon.sensor_manager import SensorManager
from everstaff.daemon.loop_manager import LoopManager
from everstaff.nulls import InMemoryStore, NullTracer


def _write_agent_yaml(agents_dir: Path, name: str, enabled: bool = True, level: str = "supervised"):
    """Helper to write a minimal autonomous agent YAML."""
    yaml_content = f"""
uuid: "{name}-uuid"
name: {name}
description: "Test agent {name}"
instructions: "You are {name}."
autonomy:
  enabled: {str(enabled).lower()}
  level: {level}
  triggers:
    - id: tick
      type: interval
      every: 3600
      task: "periodic check"
"""
    (agents_dir / f"{name}.yaml").write_text(yaml_content)


@pytest.mark.asyncio
async def test_start_discovers_autonomous_agents(tmp_path):
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    _write_agent_yaml(agents_dir, "bot-a", enabled=True)
    _write_agent_yaml(agents_dir, "bot-b", enabled=True)

    daemon = AgentDaemon(
        agents_dir=agents_dir,
        memory=InMemoryStore(),
        tracer=NullTracer(),
        llm_factory=lambda **kw: None,  # Not needed for this test
        runtime_factory=lambda **kw: None,
    )
    await daemon.start()

    assert daemon.loop_manager.has("bot-a")
    assert daemon.loop_manager.has("bot-b")

    await daemon.stop()


@pytest.mark.asyncio
async def test_ignores_non_autonomous_agents(tmp_path):
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    _write_agent_yaml(agents_dir, "bot-a", enabled=True)
    _write_agent_yaml(agents_dir, "bot-disabled", enabled=False)

    daemon = AgentDaemon(
        agents_dir=agents_dir,
        memory=InMemoryStore(),
        tracer=NullTracer(),
        llm_factory=lambda **kw: None,
        runtime_factory=lambda **kw: None,
    )
    await daemon.start()

    assert daemon.loop_manager.has("bot-a")
    assert not daemon.loop_manager.has("bot-disabled")

    await daemon.stop()


@pytest.mark.asyncio
async def test_hot_reload_starts_new_agent(tmp_path):
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    _write_agent_yaml(agents_dir, "bot-a", enabled=True)

    daemon = AgentDaemon(
        agents_dir=agents_dir,
        memory=InMemoryStore(),
        tracer=NullTracer(),
        llm_factory=lambda **kw: None,
        runtime_factory=lambda **kw: None,
    )
    await daemon.start()
    assert daemon.loop_manager.has("bot-a")
    assert not daemon.loop_manager.has("bot-new")

    # Write a new agent YAML
    _write_agent_yaml(agents_dir, "bot-new", enabled=True)
    await daemon.reload()

    assert daemon.loop_manager.has("bot-a")
    assert daemon.loop_manager.has("bot-new")

    await daemon.stop()


@pytest.mark.asyncio
async def test_hot_reload_stops_removed_agent(tmp_path):
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    _write_agent_yaml(agents_dir, "bot-a", enabled=True)
    _write_agent_yaml(agents_dir, "bot-b", enabled=True)

    daemon = AgentDaemon(
        agents_dir=agents_dir,
        memory=InMemoryStore(),
        tracer=NullTracer(),
        llm_factory=lambda **kw: None,
        runtime_factory=lambda **kw: None,
    )
    await daemon.start()
    assert daemon.loop_manager.has("bot-b")

    # Delete bot-b YAML
    (agents_dir / "bot-b.yaml").unlink()
    await daemon.reload()

    assert daemon.loop_manager.has("bot-a")
    assert not daemon.loop_manager.has("bot-b")

    await daemon.stop()


@pytest.mark.asyncio
async def test_hot_reload_autonomy_disabled(tmp_path):
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    _write_agent_yaml(agents_dir, "bot-a", enabled=True)

    daemon = AgentDaemon(
        agents_dir=agents_dir,
        memory=InMemoryStore(),
        tracer=NullTracer(),
        llm_factory=lambda **kw: None,
        runtime_factory=lambda **kw: None,
    )
    await daemon.start()
    assert daemon.loop_manager.has("bot-a")

    # Disable autonomy
    _write_agent_yaml(agents_dir, "bot-a", enabled=False)
    await daemon.reload()

    assert not daemon.loop_manager.has("bot-a")

    await daemon.stop()


@pytest.mark.asyncio
async def test_daemon_passes_channel_registry_to_loop(tmp_path):
    """AgentDaemon passes channel_registry + triggers + agent_hitl_channels to AgentLoop."""
    import yaml
    from everstaff.daemon.agent_daemon import AgentDaemon
    from everstaff.nulls import InMemoryStore, NullTracer

    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    (agents_dir / "myagent.yaml").write_text(yaml.dump({
        "agent_name": "myagent",
        "autonomy": {
            "enabled": True,
            "level": "autonomous",
            "triggers": [{"id": "t1", "type": "interval", "every": 9999, "task": "do it"}],
        },
    }))

    class _FakeChannel:
        async def send_request(self, *a): pass
        async def on_resolved(self, *a): pass
        async def start(self): pass
        async def stop(self): pass

    fake_ch = _FakeChannel()
    channel_registry = {"lark-main": fake_ch}

    loop_kwargs_captured = []
    from everstaff.daemon import agent_loop as _al_mod
    _OrigLoop = _al_mod.AgentLoop

    class _SpyLoop(_OrigLoop):
        def __init__(self, **kw):
            loop_kwargs_captured.append(kw)
            super().__init__(**kw)

    _al_mod.AgentLoop = _SpyLoop
    try:
        daemon = AgentDaemon(
            agents_dir=str(agents_dir),
            memory=InMemoryStore(),
            tracer=NullTracer(),
            llm_factory=lambda **kw: None,
            runtime_factory=lambda **kw: None,
            channel_registry=channel_registry,
        )
        await daemon.start()
        await daemon.stop()
    finally:
        _al_mod.AgentLoop = _OrigLoop

    assert len(loop_kwargs_captured) == 1
    kw = loop_kwargs_captured[0]
    assert kw["channel_registry"] is channel_registry
    assert len(kw["triggers"]) == 1
    assert kw["triggers"][0].id == "t1"

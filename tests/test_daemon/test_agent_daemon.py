"""Tests for AgentDaemon — top-level orchestrator for autonomous agent loops."""
import asyncio
import pytest
import yaml
from pathlib import Path

from everstaff.daemon.agent_daemon import AgentDaemon
from everstaff.daemon.event_bus import EventBus
from everstaff.daemon.sensor_manager import SensorManager
from everstaff.daemon.loop_manager import LoopManager
from everstaff.daemon.state_store import DaemonStateStore
from everstaff.nulls import NullTracer


class InMemoryFileStore:
    def __init__(self):
        self._data: dict[str, bytes] = {}
    async def read(self, path: str) -> bytes:
        if path not in self._data:
            raise FileNotFoundError(path)
        return self._data[path]
    async def write(self, path: str, data: bytes) -> None:
        self._data[path] = data
    async def exists(self, path: str) -> bool:
        return path in self._data
    async def delete(self, path: str) -> None:
        self._data.pop(path, None)
    async def list(self, prefix: str) -> list[str]:
        return [k for k in self._data if k.startswith(prefix)]


def _make_state_store():
    return DaemonStateStore(InMemoryFileStore())


def _write_agent_yaml(agents_dir: Path, name: str, enabled: bool = True):
    """Helper to write a minimal autonomous agent YAML."""
    yaml_content = f"""
uuid: "{name}-uuid"
name: {name}
description: "Test agent {name}"
instructions: "You are {name}."
autonomy:
  enabled: {str(enabled).lower()}
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
        daemon_state_store=_make_state_store(),
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
        daemon_state_store=_make_state_store(),
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
        daemon_state_store=_make_state_store(),
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
        daemon_state_store=_make_state_store(),
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
        daemon_state_store=_make_state_store(),
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
    """AgentDaemon passes channel_registry + triggers + hitl_channels to AgentLoop."""
    import yaml
    from everstaff.daemon.agent_daemon import AgentDaemon
    from everstaff.nulls import NullTracer

    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    (agents_dir / "myagent.yaml").write_text(yaml.dump({
        "agent_name": "myagent",
        "uuid": "myagent-uuid",
        "autonomy": {
            "enabled": True,

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
            daemon_state_store=_make_state_store(),
            tracer=NullTracer(),
            llm_factory=lambda **kw: None,
            runtime_factory=lambda **kw: None,
            channel_registry=channel_registry,
        )
        await daemon.start()
        await daemon.stop()
    finally:
        _al_mod.AgentLoop = _OrigLoop

    myagent_kwargs = [kw for kw in loop_kwargs_captured if kw["agent_name"] == "myagent"]
    assert len(myagent_kwargs) == 1
    kw = myagent_kwargs[0]
    assert kw["channel_registry"] is channel_registry
    assert len(kw["triggers"]) == 1
    assert kw["triggers"][0].id == "t1"
    assert "agent_hitl_channels" not in kw


def _write_agent_yaml_with_triggers(agents_dir: Path, name: str, triggers: list[dict]):
    """Helper to write an agent YAML with arbitrary triggers."""
    (agents_dir / f"{name}.yaml").write_text(yaml.dump({
        "agent_name": name,
        "uuid": f"{name}-uuid",
        "autonomy": {
            "enabled": True,

            "triggers": triggers,
        },
    }))


@pytest.mark.asyncio
async def test_webhook_triggers_create_webhook_sensor(tmp_path):
    """Daemon with webhook triggers and app creates a WebhookSensor."""
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    _write_agent_yaml_with_triggers(agents_dir, "hook-bot", [
        {"id": "on-push", "type": "webhook", "path": "/hook", "task": "handle push"},
    ])

    fake_app = object()  # stand-in for FastAPI app
    daemon = AgentDaemon(
        agents_dir=str(agents_dir),
        daemon_state_store=_make_state_store(),
        tracer=NullTracer(),
        llm_factory=lambda **kw: None,
        runtime_factory=lambda **kw: None,
        app=fake_app,
    )
    await daemon.start()

    # Verify that a WebhookSensor was registered
    from everstaff.daemon.sensors.webhook import WebhookSensor
    sensor_types = [type(s).__name__ for s, _ in daemon.sensor_manager._sensors]
    assert "WebhookSensor" in sensor_types

    await daemon.stop()


@pytest.mark.asyncio
async def test_webhook_triggers_skipped_without_app(tmp_path):
    """Daemon without app kwarg skips WebhookSensor even with webhook triggers."""
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    _write_agent_yaml_with_triggers(agents_dir, "hook-bot", [
        {"id": "on-push", "type": "webhook", "path": "/hook", "task": "handle push"},
    ])

    daemon = AgentDaemon(
        agents_dir=str(agents_dir),
        daemon_state_store=_make_state_store(),
        tracer=NullTracer(),
        llm_factory=lambda **kw: None,
        runtime_factory=lambda **kw: None,
        # no app= provided
    )
    await daemon.start()

    sensor_types = [type(s).__name__ for s, _ in daemon.sensor_manager._sensors]
    assert "WebhookSensor" not in sensor_types

    await daemon.stop()


@pytest.mark.asyncio
async def test_internal_triggers_create_internal_sensor(tmp_path):
    """Daemon with internal triggers creates an InternalSensor and passes it to AgentLoop."""
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    _write_agent_yaml_with_triggers(agents_dir, "int-bot", [
        {"id": "reflect", "type": "internal", "condition": "episode_count", "threshold": 5, "task": "reflect"},
    ])

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
            daemon_state_store=_make_state_store(),
            tracer=NullTracer(),
            llm_factory=lambda **kw: None,
            runtime_factory=lambda **kw: None,
        )
        await daemon.start()

        # Verify InternalSensor is registered
        from everstaff.daemon.sensors.internal import InternalSensor
        sensor_types = [type(s).__name__ for s, _ in daemon.sensor_manager._sensors]
        assert "InternalSensor" in sensor_types

        # Verify internal_sensor was passed to AgentLoop
        int_bot_kwargs = [kw for kw in loop_kwargs_captured if kw["agent_name"] == "int-bot"]
        assert len(int_bot_kwargs) == 1
        assert int_bot_kwargs[0]["internal_sensor"] is not None
        assert isinstance(int_bot_kwargs[0]["internal_sensor"], InternalSensor)

        await daemon.stop()
    finally:
        _al_mod.AgentLoop = _OrigLoop


@pytest.mark.asyncio
async def test_file_watch_triggers_create_file_watch_sensor(tmp_path):
    """Daemon with file_watch triggers creates a FileWatchSensor."""
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    _write_agent_yaml_with_triggers(agents_dir, "watch-bot", [
        {"id": "logs", "type": "file_watch", "paths": ["/tmp/logs"], "task": "check logs"},
    ])

    daemon = AgentDaemon(
        agents_dir=str(agents_dir),
        daemon_state_store=_make_state_store(),
        tracer=NullTracer(),
        llm_factory=lambda **kw: None,
        runtime_factory=lambda **kw: None,
    )
    await daemon.start()

    from everstaff.daemon.sensors.file_watch import FileWatchSensor
    sensor_types = [type(s).__name__ for s, _ in daemon.sensor_manager._sensors]
    assert "FileWatchSensor" in sensor_types

    await daemon.stop()

"""Tests for DaemonConfig, MemoryConfig, and SandboxConfig in FrameworkConfig."""
from __future__ import annotations

import pytest

from everstaff.core.config import FrameworkConfig, SandboxConfig, _load_from_dir


def test_framework_config_daemon_defaults():
    cfg = FrameworkConfig()
    assert cfg.daemon.enabled is False
    assert cfg.daemon.watch_interval == 10
    assert cfg.daemon.graceful_stop_timeout == 300
    assert cfg.daemon.max_concurrent_loops == 10


def test_framework_config_memory_defaults():
    cfg = FrameworkConfig()
    assert cfg.memory.enabled is False
    assert cfg.memory.vector_store_path == ".agent/memory/vectors"


def test_framework_config_from_yaml(tmp_path):
    config_yaml = tmp_path / "config.yaml"
    config_yaml.write_text("""
daemon:
  enabled: true
  max_concurrent_loops: 5
memory:
  enabled: true
  vector_store: chroma
""")
    cfg = _load_from_dir(tmp_path)
    assert cfg.daemon.enabled is True
    assert cfg.daemon.max_concurrent_loops == 5
    assert cfg.memory.enabled is True
    assert cfg.memory.vector_store == "chroma"


def test_daemon_config_partial_yaml(tmp_path):
    """Partial daemon config in YAML uses defaults for missing fields."""
    config_yaml = tmp_path / "config.yaml"
    config_yaml.write_text("""
daemon:
  enabled: true
""")
    cfg = _load_from_dir(tmp_path)
    assert cfg.daemon.enabled is True
    assert cfg.daemon.watch_interval == 10
    assert cfg.daemon.graceful_stop_timeout == 300
    assert cfg.daemon.max_concurrent_loops == 10


def test_daemon_config_absent_from_yaml(tmp_path):
    """If daemon section is absent from YAML, defaults apply."""
    config_yaml = tmp_path / "config.yaml"
    config_yaml.write_text("agents_dir: /tmp\n")
    cfg = _load_from_dir(tmp_path)
    assert cfg.daemon.enabled is False
    assert cfg.memory.enabled is False


class TestSandboxConfig:
    def test_default_sandbox_config(self):
        cfg = FrameworkConfig()
        assert cfg.sandbox is not None
        assert cfg.sandbox.enabled is False
        assert cfg.sandbox.type == "auto"
        assert cfg.sandbox.idle_timeout == 300
        assert cfg.sandbox.token_ttl == 30

    def test_sandbox_config_from_dict(self):
        cfg = FrameworkConfig(sandbox={"enabled": True, "type": "docker", "idle_timeout": 600})
        assert cfg.sandbox.enabled is True
        assert cfg.sandbox.type == "docker"
        assert cfg.sandbox.idle_timeout == 600

    def test_sandbox_docker_config(self):
        cfg = FrameworkConfig(sandbox={
            "enabled": True,
            "type": "docker",
            "docker": {"image": "custom:latest", "memory_limit": "1g"},
        })
        assert cfg.sandbox.docker.image == "custom:latest"
        assert cfg.sandbox.docker.memory_limit == "1g"

    def test_sandbox_extra_mounts(self):
        cfg = FrameworkConfig(sandbox={
            "enabled": True,
            "extra_mounts": [
                {"source": "/data/models", "target": "/mnt/models", "readonly": True}
            ],
        })
        assert len(cfg.sandbox.extra_mounts) == 1
        assert cfg.sandbox.extra_mounts[0].source == "/data/models"
        assert cfg.sandbox.extra_mounts[0].readonly is True

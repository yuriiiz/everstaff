"""Tests for DaemonConfig and memory_dir in FrameworkConfig."""
from __future__ import annotations

from everstaff.core.config import FrameworkConfig, _load_from_dir


def test_framework_config_daemon_defaults():
    cfg = FrameworkConfig()
    assert cfg.daemon.enabled is False
    assert cfg.daemon.watch_interval == 10
    assert cfg.daemon.graceful_stop_timeout == 300
    assert cfg.daemon.max_concurrent_loops == 10


def test_framework_config_memory_dir_default():
    cfg = FrameworkConfig()
    assert cfg.memory_dir == ".agent/memory"


def test_framework_config_from_yaml(tmp_path):
    config_yaml = tmp_path / "config.yaml"
    config_yaml.write_text("""
daemon:
  enabled: true
  max_concurrent_loops: 5
memory_dir: /custom/memory
""")
    cfg = _load_from_dir(tmp_path)
    assert cfg.daemon.enabled is True
    assert cfg.daemon.max_concurrent_loops == 5
    assert cfg.memory_dir == "/custom/memory"


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
    assert cfg.memory_dir == ".agent/memory"

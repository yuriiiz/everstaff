"""Tests for config loading strategy."""
from __future__ import annotations
import pytest
from pathlib import Path
from everstaff.core.config import load_config, FrameworkConfig


# ── Path 1: explicit config_dir ──────────────────────────────────────────────

def test_explicit_config_dir_reads_config_yaml(tmp_path):
    """When config_dir is given, reads config.yaml from that dir."""
    (tmp_path / "config.yaml").write_text("agents_dir: /custom/agents\n")
    cfg = load_config(config_dir=tmp_path)
    assert cfg.agents_dir == "/custom/agents"


def test_explicit_config_dir_reads_model_mappings(tmp_path):
    """When config_dir is given, reads model_mappings from config.yaml."""
    (tmp_path / "config.yaml").write_text(
        "model_mappings:\n"
        "  smart:\n"
        "    model_id: test-model\n"
    )
    cfg = load_config(config_dir=tmp_path)
    assert "smart" in cfg.model_mappings
    assert cfg.model_mappings["smart"].model_id == "test-model"


def test_explicit_config_dir_ignores_kwargs(tmp_path):
    """When config_dir is given, skills_dirs kwarg is ignored."""
    (tmp_path / "config.yaml").write_text("skills_dirs:\n  - /from/file\n")
    cfg = load_config(config_dir=tmp_path, skills_dirs=["/kwarg/skills"])
    assert "/kwarg/skills" not in cfg.skills_dirs
    assert "/from/file" in cfg.skills_dirs


def test_explicit_config_dir_ignores_user_config(tmp_path, monkeypatch, tmp_path_factory):
    """When config_dir is given, .agent/config.yaml is NOT read."""
    user_cfg_dir = tmp_path_factory.mktemp("home") / ".agent"
    user_cfg_dir.mkdir()
    (user_cfg_dir / "config.yaml").write_text("agents_dir: /from/user/config\n")
    monkeypatch.setattr("everstaff.core.config._user_config_path",
                        lambda: user_cfg_dir / "config.yaml")

    (tmp_path / "config.yaml").write_text("agents_dir: /from/explicit\n")
    cfg = load_config(config_dir=tmp_path)
    assert cfg.agents_dir == "/from/explicit"


# ── Path 2: three-layer merge ─────────────────────────────────────────────────

def test_no_config_dir_uses_builtin_defaults():
    """Without config_dir, returns FrameworkConfig defaults."""
    cfg = load_config()
    assert isinstance(cfg, FrameworkConfig)
    # builtin_skills should be in the skills_dirs
    assert any("builtin_skills" in d for d in cfg.skills_dirs)


def test_kwargs_skills_dirs_appended(monkeypatch):
    """skills_dirs kwarg is appended to defaults, not replaced."""
    monkeypatch.setattr("everstaff.core.config._user_config_path",
                        lambda: Path("/nonexistent/config.yaml"))
    cfg = load_config(skills_dirs=["/extra/skills"])
    dirs = cfg.skills_dirs
    assert "/extra/skills" in dirs
    # builtin still present
    assert any("builtin_skills" in d for d in dirs)


def test_user_config_skills_dirs_merged(monkeypatch, tmp_path):
    """.agent/config.yaml skills_dirs are merged between defaults and kwargs."""
    user_cfg = tmp_path / "config.yaml"
    user_cfg.write_text("skills_dirs:\n  - /user/level/skills\n")
    monkeypatch.setattr("everstaff.core.config._user_config_path", lambda: user_cfg)

    cfg = load_config(skills_dirs=["/kwarg/skills"])
    dirs = cfg.skills_dirs
    assert "/user/level/skills" in dirs
    assert "/kwarg/skills" in dirs
    assert any("builtin_skills" in d for d in dirs)
    # order: builtin < user < kwargs
    builtin_idx = next(i for i, d in enumerate(dirs) if "builtin_skills" in d)
    user_idx = dirs.index("/user/level/skills")
    kwarg_idx = dirs.index("/kwarg/skills")
    assert builtin_idx < user_idx < kwarg_idx


def test_kwargs_agents_dir_overrides(monkeypatch):
    """agents_dir kwarg overrides the default."""
    monkeypatch.setattr("everstaff.core.config._user_config_path",
                        lambda: Path("/nonexistent/config.yaml"))
    cfg = load_config(agents_dir="/my/agents")
    assert cfg.agents_dir == "/my/agents"


def test_user_config_agents_dir_overrides_default(monkeypatch, tmp_path):
    """agents_dir in .agent/config.yaml overrides the built-in default."""
    user_cfg = tmp_path / "config.yaml"
    user_cfg.write_text("agents_dir: /user/agents\n")
    monkeypatch.setattr("everstaff.core.config._user_config_path", lambda: user_cfg)
    cfg = load_config()
    assert cfg.agents_dir == "/user/agents"


def test_kwargs_agents_dir_overrides_user_config(monkeypatch, tmp_path):
    """agents_dir kwarg takes precedence over .agent/config.yaml."""
    user_cfg = tmp_path / "config.yaml"
    user_cfg.write_text("agents_dir: /user/agents\n")
    monkeypatch.setattr("everstaff.core.config._user_config_path", lambda: user_cfg)
    cfg = load_config(agents_dir="/kwarg/agents")
    assert cfg.agents_dir == "/kwarg/agents"


# ── resolve_model / has_model_kind ────────────────────────────────────────────

def test_resolve_model_returns_mapping(tmp_path):
    """resolve_model returns the correct ModelMapping for a known kind."""
    (tmp_path / "config.yaml").write_text(
        "model_mappings:\n"
        "  fast:\n"
        "    model_id: test/fast-model\n"
        "    max_tokens: 4096\n"
    )
    cfg = load_config(config_dir=tmp_path)
    mapping = cfg.resolve_model("fast")
    assert mapping.model_id == "test/fast-model"
    assert mapping.max_tokens == 4096


def test_resolve_model_raises_for_unknown_kind(tmp_path):
    """resolve_model raises ValueError for an unknown model kind."""
    (tmp_path / "config.yaml").write_text("model_mappings: {}\n")
    cfg = load_config(config_dir=tmp_path)
    with pytest.raises(ValueError, match="Unknown model_kind"):
        cfg.resolve_model("nonexistent")


def test_has_model_kind(tmp_path):
    """has_model_kind returns True/False correctly."""
    (tmp_path / "config.yaml").write_text(
        "model_mappings:\n"
        "  smart:\n"
        "    model_id: test-model\n"
    )
    cfg = load_config(config_dir=tmp_path)
    assert cfg.has_model_kind("smart") is True
    assert cfg.has_model_kind("missing") is False


# ── WebConfig ────────────────────────────────────────────────────────────────

def test_web_config_defaults():
    """WebConfig defaults to enabled=True."""
    cfg = load_config()
    assert cfg.web.enabled is True


def test_web_config_from_yaml(tmp_path):
    """web.enabled can be set via config.yaml."""
    (tmp_path / "config.yaml").write_text("web:\n  enabled: false\n")
    cfg = load_config(config_dir=tmp_path)
    assert cfg.web.enabled is False


def test_web_config_missing_from_yaml(tmp_path):
    """If web section is absent, defaults apply."""
    (tmp_path / "config.yaml").write_text("agents_dir: /tmp\n")
    cfg = load_config(config_dir=tmp_path)
    assert cfg.web.enabled is True

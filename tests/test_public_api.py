"""Tests for everstaff public API surface."""
import pytest


def test_version_exposed():
    import everstaff
    assert hasattr(everstaff, "__version__")
    assert isinstance(everstaff.__version__, str)


def test_load_config_exported():
    import everstaff
    assert callable(everstaff.load_config)


def test_create_app_exported():
    import everstaff
    assert callable(everstaff.create_app)


def test_run_cli_exported():
    import everstaff
    assert callable(everstaff.run_cli)


def test_create_app_returns_fastapi_app():
    import everstaff
    app = everstaff.create_app()
    from fastapi import FastAPI
    assert isinstance(app, FastAPI)


def test_create_app_with_config_dir(tmp_path):
    import everstaff
    (tmp_path / "config.yaml").write_text("agents_dir: /custom\n")
    app = everstaff.create_app(config_dir=tmp_path)
    from fastapi import FastAPI
    assert isinstance(app, FastAPI)
    assert app.state.config.agents_dir == "/custom"


def test_create_app_with_skills_dirs(monkeypatch):
    import everstaff
    monkeypatch.setattr("everstaff.core.config._user_config_path",
                        lambda: __import__("pathlib").Path("/nonexistent"))
    app = everstaff.create_app(skills_dirs=["/extra"])
    assert "/extra" in app.state.config.skills_dirs


def test_load_config_returns_framework_config():
    import everstaff
    cfg = everstaff.load_config()
    from everstaff.core.config import FrameworkConfig
    assert isinstance(cfg, FrameworkConfig)

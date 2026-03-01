"""Tests for web UI static file serving."""
from __future__ import annotations

import pytest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient

from everstaff.core.config import load_config


def _make_app(tmp_path: Path, *, web_enabled: bool = True):
    """Build a minimal FastAPI app with web UI config."""
    # Create fake web_static with index.html and an asset
    static_dir = tmp_path / "web_static"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<html>SPA</html>")
    assets = static_dir / "assets"
    assets.mkdir()
    (assets / "app.js").write_text("console.log('ok')")

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text(
        f"web:\n  enabled: {str(web_enabled).lower()}\n"
    )
    config = load_config(config_dir=config_dir)

    from everstaff.api import create_app
    with patch("everstaff.web_ui._resolve_static_dir", return_value=static_dir):
        app = create_app(config=config, sessions_dir=str(tmp_path / "sessions"))
    return app


def test_web_enabled_serves_index(tmp_path):
    """When web.enabled=True, GET / returns index.html."""
    app = _make_app(tmp_path, web_enabled=True)
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "SPA" in resp.text


def test_web_enabled_serves_assets(tmp_path):
    """When web.enabled=True, static assets are served."""
    app = _make_app(tmp_path, web_enabled=True)
    client = TestClient(app)
    resp = client.get("/assets/app.js")
    assert resp.status_code == 200
    assert "console.log" in resp.text


def test_web_enabled_spa_fallback(tmp_path):
    """Unknown paths return index.html for SPA routing."""
    app = _make_app(tmp_path, web_enabled=True)
    client = TestClient(app)
    resp = client.get("/some-spa-route")
    assert resp.status_code == 200
    assert "SPA" in resp.text


def test_web_enabled_api_routes_still_work(tmp_path):
    """API routes are not intercepted by SPA fallback."""
    app = _make_app(tmp_path, web_enabled=True)
    client = TestClient(app)
    resp = client.get("/api/ping")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_web_disabled_no_static(tmp_path):
    """When web.enabled=False, GET / returns 404 (no SPA)."""
    app = _make_app(tmp_path, web_enabled=False)
    client = TestClient(app)
    resp = client.get("/")
    # Should get 404 or an API error, not the SPA
    assert resp.status_code in (404, 422)


def test_web_disabled_api_still_works(tmp_path):
    """With web.enabled=False, API routes work normally."""
    app = _make_app(tmp_path, web_enabled=False)
    client = TestClient(app)
    resp = client.get("/api/ping")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_web_static_missing_logs_warning(tmp_path, caplog):
    """When web_static/ doesn't exist, logs warning and skips mount."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text("web:\n  enabled: true\n")
    config = load_config(config_dir=config_dir)

    from everstaff.api import create_app
    from unittest.mock import patch

    missing_dir = tmp_path / "nonexistent"
    with patch("everstaff.web_ui._resolve_static_dir", return_value=missing_dir):
        import logging
        with caplog.at_level(logging.WARNING, logger="everstaff.web_ui"):
            app = create_app(config=config, sessions_dir=str(tmp_path / "sessions"))

    assert "web_static/ not found" in caplog.text

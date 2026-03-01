"""Tests for POST /skills/install endpoint."""
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport
from everstaff.api import create_app
from everstaff.core.config import FrameworkConfig


@pytest.mark.asyncio
async def test_install_calls_install(tmp_path):
    """POST /skills/install must invoke SkillManager.install."""
    config = FrameworkConfig(
        sessions_dir=str(tmp_path),
        skills_dirs=[str(tmp_path / "skills"), str(tmp_path / ".agent" / "skills")],
    )
    app = create_app(config=config, sessions_dir=str(tmp_path))

    installed_path = tmp_path / "skills" / "my-skill"
    with patch("everstaff.skills.manager.SkillManager.install", new_callable=AsyncMock) as mock_install:
        mock_install.return_value = [installed_path]
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/skills/install", json={"name": "my-skill"})

    assert resp.status_code == 200
    mock_install.assert_called_once_with("my-skill")
    data = resp.json()
    assert data["name"] == "my-skill"
    assert data["status"] == "installed"
    assert str(installed_path) in data["paths"]


@pytest.mark.asyncio
async def test_install_response_includes_paths(tmp_path):
    """Install response must include paths where skills were installed."""
    config = FrameworkConfig(
        sessions_dir=str(tmp_path),
        skills_dirs=[str(tmp_path / "skills"), str(tmp_path / ".agent" / "skills")],
    )
    app = create_app(config=config, sessions_dir=str(tmp_path))

    path1 = tmp_path / "skills" / "pdf"
    path2 = tmp_path / ".agent" / "skills" / "pdf"
    with patch("everstaff.skills.manager.SkillManager.install", new_callable=AsyncMock) as mock_install:
        mock_install.return_value = [path1, path2]
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/skills/install", json={"name": "pdf"})

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["paths"]) == 2
    assert str(path1) in data["paths"]
    assert str(path2) in data["paths"]


def test_agent_skills_dir_in_default_config():
    """Default FrameworkConfig must include .agent/skills/ in skills_dirs."""
    config = FrameworkConfig()
    agent_skills = [d for d in config.skills_dirs if ".agent/skills" in d]
    assert agent_skills, f"Expected .agent/skills in skills_dirs, got: {config.skills_dirs}"


@pytest.mark.asyncio
async def test_install_returns_500_on_failure(tmp_path):
    """POST /skills/install must return 500 when install raises."""
    config = FrameworkConfig(
        sessions_dir=str(tmp_path),
        skills_dirs=[str(tmp_path / ".agent" / "skills")],
    )
    app = create_app(config=config, sessions_dir=str(tmp_path))

    with patch("everstaff.skills.manager.SkillManager.install", new_callable=AsyncMock) as mock_install:
        mock_install.side_effect = RuntimeError("npx not found")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/skills/install", json={"name": "bad-skill"})

    assert resp.status_code == 500
    assert "Install failed" in resp.json()["error"]

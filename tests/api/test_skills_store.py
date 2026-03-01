# tests/api/test_skills_store.py
import pytest
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient, ASGITransport
from api import create_app


def _make_app(tmp_path, skills_dir=None):
    from everstaff.core.config import load_config
    config = load_config()
    updates = {"sessions_dir": str(tmp_path / "sessions")}
    if skills_dir:
        updates["skills_dirs"] = [str(skills_dir)]
    config = config.model_copy(update=updates)
    (tmp_path / "sessions").mkdir(exist_ok=True)
    return create_app(config=config, sessions_dir=str(tmp_path / "sessions"))


@pytest.mark.asyncio
async def test_skills_list_no_path_field(tmp_path):
    """GET /skills should NOT expose path field."""
    skills_dir = tmp_path / "skills"
    (skills_dir / "myskill").mkdir(parents=True)
    (skills_dir / "myskill" / "SKILL.md").write_text(
        "---\nname: myskill\ndescription: Does stuff.\n---\n# My Skill\nDoes stuff.",
        encoding="utf-8",
    )
    app = _make_app(tmp_path, skills_dir=skills_dir)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/skills")
    assert resp.status_code == 200
    data = resp.json()
    # May include built-in skills; verify our skill is present and no path exposed
    assert any(s["name"] == "myskill" for s in data)
    for skill in data:
        assert "path" not in skill


@pytest.mark.asyncio
async def test_skills_store_popular(tmp_path):
    """GET /skills/store returns popular skills list."""
    app = _make_app(tmp_path)
    mock_results = [{"name": "pdf", "full_name": "org/repo@pdf", "author": "test", "url": "https://x.com", "description": "PDF skill"}]
    with patch("everstaff.skills.manager.SkillManager.search_store", new_callable=AsyncMock, return_value=mock_results):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/skills/store")
    assert resp.status_code == 200
    assert resp.json() == mock_results


@pytest.mark.asyncio
async def test_skills_store_search(tmp_path):
    """GET /skills/store?query=xxx passes query to search_store."""
    app = _make_app(tmp_path)
    mock_results = [{"name": "github", "full_name": "org/repo@github", "author": "test", "url": "https://x.com", "description": "Github"}]
    with patch("everstaff.skills.manager.SkillManager.search_store", new_callable=AsyncMock, return_value=mock_results) as mock_search:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/skills/store?query=github")
    assert resp.status_code == 200
    assert resp.json()[0]["name"] == "github"
    mock_search.assert_called_once_with("github")


@pytest.mark.asyncio
async def test_skills_store_not_shadowed_by_name_route(tmp_path):
    """Ensure /skills/store is not treated as GET /skills/{name}."""
    app = _make_app(tmp_path)
    with patch("everstaff.skills.manager.SkillManager.search_store", new_callable=AsyncMock, return_value=[]):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/skills/store")
    # If routing is wrong, this returns 404 (skill 'store' not found). Must be 200.
    assert resp.status_code == 200

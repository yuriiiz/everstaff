# tests/api/test_error_responses.py
import pytest
from httpx import AsyncClient, ASGITransport
from everstaff.api import create_app


@pytest.mark.asyncio
async def test_404_returns_error_response(tmp_path):
    app = create_app(sessions_dir=str(tmp_path))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/sessions/nonexistent-id-999")
    assert resp.status_code == 404
    body = resp.json()
    assert "error" in body
    assert isinstance(body["error"], str)


@pytest.mark.asyncio
async def test_422_returns_error_response(tmp_path):
    app = create_app(sessions_dir=str(tmp_path))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Send invalid JSON body to an endpoint that expects one
        resp = await client.post("/api/sessions/fake-id/resume", content="not-json", headers={"Content-Type": "application/json"})
    assert resp.status_code == 422
    body = resp.json()
    assert "error" in body

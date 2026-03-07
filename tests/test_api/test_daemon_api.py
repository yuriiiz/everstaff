import pytest
from httpx import AsyncClient, ASGITransport


@pytest.fixture
def app_with_daemon():
    """Create a FastAPI app with daemon routes and a mock daemon."""
    from fastapi import FastAPI
    from everstaff.api.daemon import daemon_router
    from everstaff.daemon.loop_manager import LoopManager

    app = FastAPI()
    app.include_router(daemon_router)

    # Mock daemon on app.state
    class MockSensorManager:
        _sensors = []

    class MockDaemon:
        is_running = True
        loop_manager = LoopManager()
        sensor_manager = MockSensorManager()

        async def reload(self):
            pass

    app.state.daemon = MockDaemon()
    return app


@pytest.mark.asyncio
async def test_daemon_status(app_with_daemon):
    async with AsyncClient(transport=ASGITransport(app=app_with_daemon), base_url="http://test") as client:
        resp = await client.get("/api/daemon/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "enabled" in data
        assert data["enabled"] is True
        assert data["webhooks"] == []


@pytest.mark.asyncio
async def test_daemon_loops_list(app_with_daemon):
    async with AsyncClient(transport=ASGITransport(app=app_with_daemon), base_url="http://test") as client:
        resp = await client.get("/api/daemon/loops")
        assert resp.status_code == 200
        assert "loops" in resp.json()


@pytest.mark.asyncio
async def test_daemon_reload(app_with_daemon):
    async with AsyncClient(transport=ASGITransport(app=app_with_daemon), base_url="http://test") as client:
        resp = await client.post("/api/daemon/reload")
        assert resp.status_code == 200

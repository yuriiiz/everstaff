"""Daemon management API routes."""
from __future__ import annotations

import logging
from fastapi import APIRouter, Request

logger = logging.getLogger(__name__)

daemon_router = APIRouter(prefix="/api/daemon", tags=["daemon"])


@daemon_router.get("/status")
async def daemon_status(request: Request):
    daemon = getattr(request.app.state, "daemon", None)
    if daemon is None:
        logger.debug("daemon not configured")
        return {"enabled": False, "running": False, "webhooks": []}
    webhooks = []
    for sensor, agent_name in daemon.sensor_manager._sensors:
        if hasattr(sensor, "_route_path") and sensor._route_path:
            webhooks.append({
                "agent_name": agent_name,
                "path": sensor._route_path,
            })
    status = {"enabled": True, "running": daemon.is_running, "webhooks": webhooks}
    logger.debug("status=%s", status)
    return status


@daemon_router.get("/loops")
async def daemon_loops(request: Request):
    daemon = getattr(request.app.state, "daemon", None)
    if daemon is None:
        return {"loops": {}}
    loops = daemon.loop_manager.get_status()
    logger.debug("loops=%d", len(loops))
    return {"loops": loops}


@daemon_router.post("/reload")
async def daemon_reload(request: Request):
    daemon = getattr(request.app.state, "daemon", None)
    if daemon is None:
        logger.warning("reload requested but daemon not running")
        return {"status": "daemon not running"}
    logger.info("triggering hot reload")
    await daemon.reload()
    loops = daemon.loop_manager.get_status()
    logger.info("reload complete loops=%d", len(loops))
    return {"status": "reloaded", "loops": loops}

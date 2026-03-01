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
        logger.debug("[DaemonAPI] GET /status — daemon not configured")
        return {"enabled": False, "running": False}
    status = {"enabled": True, "running": daemon.is_running}
    logger.debug("[DaemonAPI] GET /status — %s", status)
    return status


@daemon_router.get("/loops")
async def daemon_loops(request: Request):
    daemon = getattr(request.app.state, "daemon", None)
    if daemon is None:
        return {"loops": {}}
    loops = daemon.loop_manager.get_status()
    logger.debug("[DaemonAPI] GET /loops — %d loop(s)", len(loops))
    return {"loops": loops}


@daemon_router.post("/reload")
async def daemon_reload(request: Request):
    daemon = getattr(request.app.state, "daemon", None)
    if daemon is None:
        logger.warning("[DaemonAPI] POST /reload — daemon not running")
        return {"status": "daemon not running"}
    logger.info("[DaemonAPI] POST /reload — triggering hot reload")
    await daemon.reload()
    loops = daemon.loop_manager.get_status()
    logger.info("[DaemonAPI] POST /reload — complete, %d loop(s) active", len(loops))
    return {"status": "reloaded", "loops": loops}

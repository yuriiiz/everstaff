"""Serve the bundled frontend when web.enabled=True."""
from __future__ import annotations

import importlib.resources as _pkg_resources
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse

_logger = logging.getLogger(__name__)


def _resolve_static_dir() -> Path:
    """Locate the web_static directory inside the installed package."""
    return Path(str(_pkg_resources.files("everstaff") / "web_static"))


def mount_web_ui(app: FastAPI) -> None:
    """Mount frontend static files with SPA fallback.

    Must be called AFTER all API routers are registered so that
    API routes take priority over the catch-all SPA fallback.
    """
    static_dir = _resolve_static_dir()

    if not static_dir.exists():
        _logger.warning(
            "web.enabled=true but web_static/ not found at %s. "
            "Skipping UI mount. Run 'make build-web' to build the frontend.",
            static_dir,
        )
        return

    # Serve hashed assets (js, css, images) with caching
    assets_dir = static_dir / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="web-assets")

    index_html = static_dir / "index.html"

    # SPA fallback: any path not matched by API routers returns index.html
    @app.get("/{path:path}")
    async def _spa_fallback(path: str):
        # Serve actual files if they exist (e.g. favicon.ico, robots.txt)
        candidate = static_dir / path
        if candidate.is_file() and ".." not in path:
            return FileResponse(str(candidate))
        return FileResponse(str(index_html))

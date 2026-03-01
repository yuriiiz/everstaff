from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger(__name__)


def _guard_session_id(sessions_dir: Path, session_id: str) -> Path:
    target = (sessions_dir / session_id).resolve()
    if not str(target).startswith(str(sessions_dir) + "/"):
        raise HTTPException(status_code=400, detail="Invalid session_id")
    return target


def make_router(config) -> APIRouter:
    sessions_dir = Path(config.sessions_dir).expanduser().resolve()
    router = APIRouter(tags=["traces"])

    @router.get("/traces")
    async def get_global_traces(
        session_id: str | None = Query(None),
        limit: int = Query(500),
    ) -> list[dict]:
        global_path = sessions_dir / "traces.jsonl"
        if not global_path.exists():
            return []
        all_lines = global_path.read_text().strip().splitlines()
        events = []
        for line in all_lines:
            try:
                ev = json.loads(line)
                if session_id is None or ev.get("session_id") == session_id:
                    events.append(ev)
            except Exception as exc:
                logger.debug("Failed to parse trace line: %s", exc)
        return events[-limit:]

    @router.get("/sessions/{session_id}/traces")
    async def get_session_traces(session_id: str, limit: int = Query(500)) -> list[dict]:
        session_dir = _guard_session_id(sessions_dir, session_id)
        path = session_dir / "traces.jsonl"
        if not path.exists():
            raise HTTPException(status_code=404, detail="No traces for this session")
        lines = path.read_text().strip().splitlines()[-limit:]
        events = []
        for line in lines:
            try:
                events.append(json.loads(line))
            except Exception as exc:
                logger.debug("Failed to parse trace line: %s", exc)
        return events

    return router

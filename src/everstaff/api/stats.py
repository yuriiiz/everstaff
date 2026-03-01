"""Stats API — aggregate and per-session statistics."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)


def make_router(config) -> APIRouter:
    sessions_dir = Path(config.sessions_dir).expanduser().resolve()
    router = APIRouter(tags=["stats"], prefix="/stats")

    @router.get("")
    async def get_aggregate_stats(request: Request) -> dict:
        """Aggregate stats across all sessions."""
        total_sessions = 0
        total_tool_calls = 0
        total_errors = 0
        tokens_by_model: dict[str, dict] = {}
        agents_count = 0
        skills_count = 0
        pending_hitl_count = 0

        # 1. Count Sessions and Tool/Token usage
        if sessions_dir.exists():
            for session_dir in sessions_dir.iterdir():
                if not session_dir.is_dir():
                    continue
                meta_path = session_dir / "session.json"
                if not meta_path.exists():
                    continue
                try:
                    raw = json.loads(meta_path.read_text())
                    meta = raw.get("metadata", {})
                    total_sessions += 1
                    total_tool_calls += meta.get("tool_calls_count", 0)
                    total_errors += meta.get("errors_count", 0)
                    for call in meta.get("own_calls", []) + meta.get("children_calls", []):
                        model = call.get("model_id", "unknown")
                        if model not in tokens_by_model:
                            tokens_by_model[model] = {
                                "input_tokens": 0,
                                "output_tokens": 0,
                                "total_tokens": 0,
                                "calls": 0,
                            }
                        tokens_by_model[model]["input_tokens"] += call.get("input_tokens", 0)
                        tokens_by_model[model]["output_tokens"] += call.get("output_tokens", 0)
                        tokens_by_model[model]["total_tokens"] += call.get("total_tokens", 0)
                        tokens_by_model[model]["calls"] += 1

                    # Count pending HITL
                    if raw.get("status") == "waiting_for_human":
                        for item in raw.get("hitl_requests", []):
                            if item.get("status") == "pending":
                                from everstaff.api.hitl import _is_expired
                                if not _is_expired(item):
                                    pending_hitl_count += 1
                except Exception as exc:
                    logger.debug("Failed to read session stats %s: %s", session_dir.name, exc)

        # 2. Count Agents
        try:
            agents_dir = Path(config.agents_dir).expanduser().resolve()
            if agents_dir.exists():
                agents_count = len(list(agents_dir.glob("*.yaml")))
        except Exception:
            pass

        # 3. Count Skills
        try:
            from everstaff.api.skills import make_router as make_skills_router
            # We can't easily call list_skills without a router, but we can use the same logic
            skills_dirs = list(config.skills_dirs)
            from everstaff.skills.manager import SkillManager
            mgr = SkillManager(skills_dirs)
            skills_count = len(mgr.list())
        except Exception:
            pass

        return {
            "total_sessions": total_sessions,
            "total_tool_calls": total_tool_calls,
            "total_errors": total_errors,
            "tokens_by_model": tokens_by_model,
            "agents_count": agents_count,
            "skills_count": skills_count,
            "pending_hitl_count": pending_hitl_count,
        }

    @router.get("/sessions/{session_id}")
    async def get_session_stats(session_id: str) -> dict:
        """Per-session stats from session.json metadata."""
        target = (sessions_dir / session_id).resolve()
        if not str(target).startswith(str(sessions_dir) + "/"):
            raise HTTPException(status_code=400, detail="Invalid session_id")
        meta_path = target / "session.json"
        if not meta_path.exists():
            raise HTTPException(status_code=404, detail="Session not found")
        raw = json.loads(meta_path.read_text())
        return {
            "session_id": session_id,
            "agent_name": raw.get("agent_name"),
            "status": raw.get("status", "unknown"),
            "metadata": raw.get("metadata", {}),
        }

    return router

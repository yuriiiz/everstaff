from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from pydantic import BaseModel

from everstaff.schema.memory import Session
from everstaff.schema.api_models import SessionMetadata
from everstaff.core.constants import STALE_SESSION_THRESHOLD_SECONDS

logger = logging.getLogger(__name__)

RESUMABLE_STATES = {"waiting_for_human", "paused", "cancelled", "failed", "interrupted"}

# Well-known builtin agent UUIDs that don't appear in YAML files
_BUILTIN_UUID_TO_NAME: dict[str, str] = {
    "builtin_agent_creator": "Agent Creator",
    "builtin_skill_creator": "Skill Creator",
}


def _guard_session_id(sessions_dir: Path, session_id: str) -> Path:
    """Resolve session directory and guard against path traversal."""
    target = (sessions_dir / session_id).resolve()
    if not str(target).startswith(str(sessions_dir) + "/"):
        raise HTTPException(status_code=400, detail="Invalid session_id")
    return target


def _format_decision_message(request: dict, decision: str, comment: str | None) -> str:
    lines = ["[Human decision for HITL request]"]
    lines.append(f"Original prompt: {request.get('prompt', '')}")
    lines.append(f"Decision: {decision}")
    if comment:
        lines.append(f"Comment: {comment}")
    return "\n".join(lines)


async def _resume_session_task(
    session_id: str,
    agent_name: str,
    decision_text: str,
    config,
    tool_call_id: str = "",
    broadcast_fn=None,   # optional async callable(dict) -> None
    channel_manager=None,  # ChannelManager for HITL broadcast
) -> None:
    from everstaff.builder.agent_builder import AgentBuilder
    from everstaff.builder.environment import DefaultEnvironment

    sessions_dir = Path(config.sessions_dir).expanduser().resolve()
    agents_dir = Path(config.agents_dir).expanduser().resolve()
    agent_path = (agents_dir / f"{agent_name}.yaml").resolve()
    # Guard against path traversal via malicious agent_name in session.json
    if not str(agent_path).startswith(str(agents_dir) + "/"):
        logger.error("Resume: invalid agent_name '%s' in session.json", agent_name)
        return

    if not agent_path.exists():
        # Fall back to builtin agents
        from everstaff.core.config import _builtin_agents_path
        builtin_p = _builtin_agents_path()
        if builtin_p:
            builtin_candidate = (Path(builtin_p) / f"{agent_name}.yaml").resolve()
            if builtin_candidate.is_relative_to(Path(builtin_p)) and builtin_candidate.exists():
                agent_path = builtin_candidate
    if not agent_path.exists():
        logger.error("Resume: agent spec not found for %s", agent_name)
        return

    from everstaff.utils.yaml_loader import load_yaml
    from everstaff.schema.agent_spec import AgentSpec
    spec = AgentSpec(**load_yaml(str(agent_path)))

    env = DefaultEnvironment(
        sessions_dir=str(sessions_dir),
        config=config,
        channel_manager=channel_manager,
    )
    _sid = session_id[:8]
    logger.info("[session] start  agent=%s  session=%s", agent_name, _sid)
    runtime, ctx = await AgentBuilder(spec, env, session_id=session_id).build()
    try:
        if tool_call_id:
            # Proper resume (single-HITL legacy path): insert HITL decision as a tool-role message.
            from everstaff.protocols import Message
            mem = env.build_memory_store()
            messages = await mem.load(session_id)
            messages.append(Message(role="tool", content=decision_text, tool_call_id=tool_call_id))
            await mem.save(session_id, messages)
            input_text = None
        elif not decision_text:
            # New path: read all resolved HITL responses from session.json
            session_path = sessions_dir / session_id / "session.json"
            input_text = None
            if session_path.exists():
                try:
                    session_raw = json.loads(session_path.read_text())
                    resolved_hitls = [
                        item for item in session_raw.get("hitl_requests", [])
                        if item.get("status") == "resolved" and item.get("response")
                    ]
                    if resolved_hitls:
                        from everstaff.protocols import Message
                        mem = env.build_memory_store()
                        messages = await mem.load(session_id)
                        for item in resolved_hitls:
                            req = item.get("request", {})
                            resp = item.get("response", {})
                            dtxt = _format_decision_message(req, resp.get("decision", ""), resp.get("comment"))
                            tc_id = item.get("tool_call_id", "")
                            messages.append(Message(role="tool", content=dtxt, tool_call_id=tc_id))
                        await mem.save(session_id, messages)

                        # Process grant_scope for tool_permission resolutions
                        extra_perms = []
                        for item in resolved_hitls:
                            req = item.get("request", {})
                            resp = item.get("response", {})
                            if req.get("type") == "tool_permission" and resp.get("decision") == "approved":
                                grant_scope = resp.get("grant_scope", "once")
                                tool_name = req.get("tool_name", "")
                                if not tool_name:
                                    continue
                                if grant_scope in ("session", "permanent"):
                                    extra_perms.append(tool_name)
                                if grant_scope == "permanent":
                                    try:
                                        from everstaff.permissions.definition_writer import YamlAgentDefinitionWriter
                                        writer = YamlAgentDefinitionWriter(agents_dir=str(agents_dir))
                                        await writer.add_allow_permission(agent_name, tool_name)
                                    except Exception as wr_err:
                                        logger.warning("Failed to write permanent grant for %s: %s", tool_name, wr_err)

                        if extra_perms:
                            # Merge with existing session grants (additive)
                            existing = session_raw.get("extra_permissions", [])
                            merged = list(dict.fromkeys(existing + extra_perms))  # deduplicate, preserve order
                            await mem.save(session_id, messages, extra_permissions=merged)
                except Exception as read_err:
                    logger.warning("[session] failed to read session.json for HITL resume  session=%s  err=%s",
                                   _sid, read_err)
        else:
            # Legacy path: no tool_call_id stored (old sessions), fall back to user message
            input_text = decision_text

        async for event in runtime.run_stream(input_text):
            if broadcast_fn is not None:
                try:
                    await broadcast_fn({**event.model_dump(), "session_id": session_id})
                except Exception as exc:
                    logger.debug("[session] broadcast failed  session=%s  event=%s  err=%s",
                                 _sid, type(event).__name__, exc)
        logger.info("[session] end agent=%s session=%s", agent_name, _sid)
    except Exception as e:
        logger.error("[session] error agent=%s session=%s err=%s", agent_name, _sid, e)
    finally:
        await ctx.aclose()


def _extract_broadcast_fn(channel_manager):
    """Extract _broadcast callable from the registered WebSocketChannel, if any."""
    from everstaff.channels.websocket import WebSocketChannel
    try:
        for ch in channel_manager._channels:
            if isinstance(ch, WebSocketChannel):
                return ch._broadcast
    except AttributeError:
        pass
    return None


class ResumeRequest(BaseModel):
    user_input: str = ""
    decision: str | None = None  # for HITL flow (deprecated path, use /hitl/{id}/resolve instead)
    comment: str | None = None


class StartSessionRequest(BaseModel):
    agent_name: str | None = None
    agent_uuid: str | None = None
    user_input: str = ""


def _parse_session_metadata(raw_metadata: dict) -> SessionMetadata:
    """Parse raw metadata dict into SessionMetadata, ignoring unknown fields."""
    try:
        return SessionMetadata.model_validate(raw_metadata)
    except Exception as exc:
        logger.debug("Failed to parse session metadata: %s", exc)
        return SessionMetadata()


def make_router(config) -> APIRouter:
    sessions_dir = Path(config.sessions_dir).expanduser().resolve()
    router = APIRouter(tags=["sessions"])

    @router.post("/sessions", status_code=202)
    async def start_session(
        body: StartSessionRequest,
        request: Request,
        background_tasks: BackgroundTasks,
    ) -> dict:
        agents_dir_path = Path(config.agents_dir).expanduser().resolve()
        agent_name = body.agent_name

        from everstaff.core.config import _builtin_agents_path as _bap
        builtin_agents_dir = Path(_bap()) if _bap() else None

        if not agent_name and body.agent_uuid:
            # Resolve UUID to agent_name by scanning user agents then builtins
            from everstaff.utils.yaml_loader import load_yaml
            for scan_dir in [agents_dir_path, builtin_agents_dir]:
                if not scan_dir or not scan_dir.exists():
                    continue
                for f in scan_dir.glob("*.yaml"):
                    try:
                        spec = load_yaml(str(f))
                        if spec.get("uuid") == body.agent_uuid:
                            agent_name = spec.get("agent_name")
                            break
                    except Exception:
                        continue
                if agent_name:
                    break

        if not agent_name:
            raise HTTPException(status_code=400, detail="agent_name or valid agent_uuid is required")

        # Resolve agent path: user agents_dir takes precedence, then builtin
        agent_path = (agents_dir_path / f"{agent_name}.yaml").resolve()
        if not agent_path.is_relative_to(agents_dir_path):
            raise HTTPException(status_code=400, detail="Invalid agent name")
        if not agent_path.exists() and builtin_agents_dir:
            builtin_candidate = (builtin_agents_dir / f"{agent_name}.yaml").resolve()
            if builtin_candidate.is_relative_to(builtin_agents_dir) and builtin_candidate.exists():
                agent_path = builtin_candidate
        if not agent_path.exists():
            raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found")
        session_id = str(uuid4())
        cm = getattr(request.app.state, "channel_manager", None)
        broadcast_fn = _extract_broadcast_fn(cm) if cm is not None else None
        background_tasks.add_task(
            _resume_session_task, session_id, agent_name, body.user_input, config,
            broadcast_fn=broadcast_fn,
            channel_manager=cm,
        )
        return {"session_id": session_id, "status": "running"}

    @router.get("/sessions", response_model=list[Session])
    async def list_sessions(
        status: str | None = Query(default=None),
        agent_name: str | None = Query(default=None),
        agent_uuid: str | None = Query(default=None),
    ) -> list[Session]:
        sessions = []
        if not sessions_dir.exists():
            return sessions
        for d in sorted(sessions_dir.iterdir()):
            if not d.is_dir():
                continue
            meta_path = d / "session.json"
            if meta_path.exists():
                try:
                    raw = json.loads(meta_path.read_text())
                    status_val = raw.get("status", "unknown")

                    # Detect interrupted: running session with no active cancel.signal and stale
                    if status_val == "running":
                        is_cancel_active = (d / "cancel.signal").exists()
                        if not is_cancel_active:
                            try:
                                updated_at = datetime.fromisoformat(raw.get("updated_at", ""))
                                age = (datetime.now(timezone.utc) - updated_at).total_seconds()
                                if age > STALE_SESSION_THRESHOLD_SECONDS:
                                    status_val = "interrupted"
                            except Exception:
                                pass

                    raw_agent_name = raw.get("agent_name", "")
                    raw_agent_uuid = raw.get("agent_uuid") # May not exist in old sessions
                    # Apply filters
                    if status is not None and status_val != status:
                        continue
                    if agent_name is not None and raw_agent_name != agent_name:
                        continue
                    if agent_uuid is not None and raw_agent_uuid != agent_uuid:
                        continue

                    session_obj = Session(
                        session_id=raw.get("session_id", d.name),
                        parent_session_id=raw.get("parent_session_id"),
                        agent_name=raw.get("agent_name", ""),
                        agent_uuid=raw.get("agent_uuid"),
                        created_at=raw.get("created_at", ""),
                        updated_at=raw.get("updated_at", ""),
                        status=status_val,
                        active=False,
                        metadata=_parse_session_metadata(raw.get("metadata", {})),
                        hitl_requests=raw.get("hitl_requests", []),
                        # messages NOT included in list response
                    )

                    sessions.append(session_obj)
                except Exception as exc:
                    logger.debug("Failed to read session metadata %s: %s", d, exc)

        return sessions

    @router.get("/sessions/{session_id}", response_model=Session)
    async def get_session(session_id: str) -> Session:
        session_dir = _guard_session_id(sessions_dir, session_id)
        meta_path = session_dir / "session.json"
        if not meta_path.exists():
            raise HTTPException(status_code=404, detail="Session not found")
        try:
            raw = json.loads(meta_path.read_text())
        except Exception:
            raise HTTPException(status_code=500, detail="Failed to read session metadata")

        # Detect interrupted status
        status_val = raw.get("status", "unknown")
        if status_val == "running":
            is_cancel_active = (session_dir / "cancel.signal").exists()
            if not is_cancel_active:
                try:
                    updated_at = datetime.fromisoformat(raw.get("updated_at", ""))
                    age = (datetime.now(timezone.utc) - updated_at).total_seconds()
                    if age > STALE_SESSION_THRESHOLD_SECONDS:
                        status_val = "interrupted"
                except Exception:
                    pass

        return Session(
            session_id=raw.get("session_id", session_id),
            parent_session_id=raw.get("parent_session_id"),
            agent_name=raw.get("agent_name", ""),
            agent_uuid=raw.get("agent_uuid"),
            created_at=raw.get("created_at", ""),
            updated_at=raw.get("updated_at", ""),
            status=status_val,
            active=False,
            messages=raw.get("messages", []),
            metadata=_parse_session_metadata(raw.get("metadata", {})),
            hitl_requests=raw.get("hitl_requests", []),
        )

    @router.delete("/sessions/{session_id}", status_code=204)
    async def delete_session(session_id: str) -> None:
        d = _guard_session_id(sessions_dir, session_id)
        if not d.exists():
            raise HTTPException(status_code=404, detail="Session not found")
        try:
            shutil.rmtree(d)
        except (FileNotFoundError, OSError) as e:
            logger.warning("Failed to delete session %s: %s", session_id, e)
        logger.info("Deleted session %s", session_id)

    @router.post("/sessions/{session_id}/stop")
    async def stop_session(request: Request, session_id: str, force: bool = False) -> dict:
        # Validate session exists before writing signal
        session_dir = _guard_session_id(sessions_dir, session_id)
        if not (session_dir / "session.json").exists():
            raise HTTPException(status_code=404, detail="Session not found")
        store = request.app.state.file_store
        signal_path = f"{session_id}/cancel.signal"
        payload = json.dumps({"force": force}).encode()
        await store.write(signal_path, payload)
        return {"status": "cancelled", "force": force, "session_id": session_id}

    @router.post("/sessions/{session_id}/resume", status_code=202)
    async def resume_session(
        request: Request,
        session_id: str,
        background_tasks: BackgroundTasks,
        body: ResumeRequest | None = None,
    ) -> dict:
        session_path = _guard_session_id(sessions_dir, session_id) / "session.json"

        if not session_path.exists():
            raise HTTPException(status_code=404, detail="Session not found")

        session_raw = json.loads(session_path.read_text())
        current_status = session_raw.get("status", "unknown")

        # Apply the same interrupted detection as list_sessions
        if current_status == "running":
            session_dir_resume = _guard_session_id(sessions_dir, session_id)
            is_cancel_active = (session_dir_resume / "cancel.signal").exists()
            if not is_cancel_active:
                try:
                    updated_at = datetime.fromisoformat(session_raw.get("updated_at", ""))
                    age = (datetime.now(timezone.utc) - updated_at).total_seconds()
                    if age > STALE_SESSION_THRESHOLD_SECONDS:
                        current_status = "interrupted"
                except Exception:
                    pass

        if current_status not in RESUMABLE_STATES:
            raise HTTPException(
                status_code=409,
                detail=f"Session status '{current_status}' is not resumable",
            )

        agent_name = session_raw.get("agent_name", "")
        cm = getattr(request.app.state, "channel_manager", None)

        # For cancelled/failed/interrupted: resume with optional user input
        if current_status in ("cancelled", "failed", "interrupted"):
            user_input = (body.user_input if body else "") or ""
            background_tasks.add_task(
                _resume_session_task, session_id, agent_name, user_input, config,
                broadcast_fn=_extract_broadcast_fn(cm) if cm is not None else None,
                channel_manager=cm,
            )
            return {"status": "resuming", "session_id": session_id}

        # For waiting_for_human/paused: check all HITL requests are resolved
        hitl_requests = session_raw.get("hitl_requests", [])
        pending = [r for r in hitl_requests if r.get("status") == "pending"]
        if pending:
            raise HTTPException(
                status_code=409,
                detail=f"HITL request(s) not yet resolved ({len(pending)} pending). Call POST /hitl/{{hitl_id}}/resolve first",
            )

        background_tasks.add_task(
            _resume_session_task, session_id, agent_name, "", config,
            broadcast_fn=_extract_broadcast_fn(cm) if cm is not None else None,
            channel_manager=cm,
        )
        return {"status": "resuming", "session_id": session_id}

    return router

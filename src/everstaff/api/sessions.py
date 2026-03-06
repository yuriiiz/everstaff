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

# Well-known builtin agent UUIDs → display names
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
    agent_uuid: str = "",
    mcp_pool=None,  # McpConnectionPool for cross-session connection reuse
) -> None:
    from everstaff.builder.agent_builder import AgentBuilder
    from everstaff.builder.environment import DefaultEnvironment
    from everstaff.protocols import HumanApprovalRequired

    sessions_dir = Path(config.sessions_dir).expanduser().resolve()
    agents_dir = Path(config.agents_dir).expanduser().resolve()

    agent_path = None

    # Try resolving by agent_uuid first (O(1) lookup for uuid-based filenames)
    if agent_uuid:
        candidate = (agents_dir / f"{agent_uuid}.yaml").resolve()
        if candidate.is_relative_to(agents_dir) and candidate.exists():
            agent_path = candidate

    # Fall back to agent_name-based lookup
    if not agent_path:
        candidate = (agents_dir / f"{agent_name}.yaml").resolve()
        if str(candidate).startswith(str(agents_dir) + "/") and candidate.exists():
            agent_path = candidate

    # Fall back to scanning user agents by uuid inside YAML
    if not agent_path and agent_uuid and agents_dir.exists():
        from everstaff.utils.yaml_loader import load_yaml
        for f in agents_dir.glob("*.yaml"):
            try:
                if load_yaml(str(f)).get("uuid") == agent_uuid:
                    agent_path = f
                    break
            except Exception:
                pass

    # Fall back to builtin agents
    if not agent_path:
        from everstaff.core.config import _builtin_agents_path
        builtin_p = _builtin_agents_path()
        if builtin_p:
            builtin_dir = Path(builtin_p)
            if builtin_dir.exists():
                # Try UUID-based builtin: {uuid}.yaml
                if agent_uuid:
                    builtin_candidate = (builtin_dir / f"{agent_uuid}.yaml").resolve()
                    if builtin_candidate.is_relative_to(builtin_dir) and builtin_candidate.exists():
                        agent_path = builtin_candidate
                # Scan builtins by agent_name or uuid inside YAML
                if not agent_path:
                    from everstaff.utils.yaml_loader import load_yaml
                    for f in builtin_dir.glob("*.yaml"):
                        try:
                            spec = load_yaml(str(f))
                            if (agent_uuid and spec.get("uuid") == agent_uuid) or \
                               (agent_name and spec.get("agent_name") == agent_name):
                                agent_path = f
                                break
                        except Exception:
                            pass

    if not agent_path:
        logger.error("Resume: agent spec not found for %s (uuid=%s)", agent_name, agent_uuid)
        return

    from everstaff.utils.yaml_loader import load_yaml
    from everstaff.schema.agent_spec import AgentSpec
    spec = AgentSpec(**load_yaml(str(agent_path)))

    env = DefaultEnvironment(
        sessions_dir=str(sessions_dir),
        config=config,
        channel_manager=channel_manager,
        mcp_pool=mcp_pool,
    )
    _sid = session_id[:8]

    # Clear any leftover cancel.signal before building the runtime.
    # This prevents the new runtime from immediately self-cancelling
    # when resumed right after a stop (before the old runtime cleaned up).
    _cancel_file = sessions_dir / session_id / "cancel.signal"
    try:
        if _cancel_file.exists():
            _cancel_file.unlink()
            logger.debug("[session] cleared leftover cancel.signal  session=%s", _sid)
    except Exception:
        pass

    logger.info("[session] start  agent=%s  session=%s", agent_name, _sid)

    # Ensure session.json exists and status is "running" BEFORE build(),
    # so the session is always visible in the UI — even if build() crashes.
    _session_dir = sessions_dir / session_id
    _session_dir.mkdir(parents=True, exist_ok=True)
    _meta = _session_dir / "session.json"
    if _meta.exists():
        # Resume: reset status to "running" and clear previous error.
        try:
            _existing = json.loads(_meta.read_text())
            _existing["status"] = "running"
            _existing["updated_at"] = datetime.now(timezone.utc).isoformat()
            _existing.pop("error", None)
            _meta.write_text(json.dumps(_existing, indent=2))
        except Exception:
            pass
    else:
        # New session: write initial session.json.
        _now = datetime.now(timezone.utc).isoformat()
        _meta.write_text(json.dumps({
            "session_id": session_id,
            "agent_name": agent_name,
            "agent_uuid": agent_uuid,
            "status": "running",
            "created_at": _now,
            "updated_at": _now,
            "parent_session_id": None,
            "metadata": {"title": agent_name},
            "messages": [],
            "hitl_requests": [],
        }, indent=2))

    ctx = None
    try:
        runtime, ctx = await AgentBuilder(spec, env, session_id=session_id).build()
        if tool_call_id:
            # Proper resume (single-HITL legacy path): insert HITL decision as a tool-role message.
            from everstaff.protocols import Message
            mem = env.build_memory_store()
            messages = await mem.load(session_id)
            messages.append(Message(role="tool", content=decision_text, tool_call_id=tool_call_id, created_at=datetime.now(timezone.utc).isoformat()))
            await mem.save(session_id, messages)
            input_text = None
        elif not decision_text:
            # New path: read all resolved HITL responses from session.json
            session_path = sessions_dir / session_id / "session.json"
            input_text = None
            if session_path.exists():
                try:
                    session_raw = json.loads(session_path.read_text())
                    hitl_requests = session_raw.get("hitl_requests", [])
                    resolved_hitls = [
                        item for item in hitl_requests
                        if item.get("status") == "resolved" and item.get("response")
                    ]
                    pending_hitls = [
                        item for item in hitl_requests
                        if item.get("status") == "pending"
                    ]
                    # Guard: if there are pending HITLs and nothing resolved to
                    # process, abort — the session is still waiting for human input.
                    # Without this guard, runtime.run_stream(None) would drop the
                    # dangling tool calls, silently auto-rejecting the HITL.
                    if pending_hitls and not resolved_hitls:
                        logger.warning(
                            "[session] aborting resume for session %s: "
                            "%d pending HITL(s) with no resolved ones to process",
                            _sid, len(pending_hitls),
                        )
                        return
                    if resolved_hitls:
                        from everstaff.protocols import Message
                        from everstaff.tools.pipeline import ToolCallContext
                        mem = env.build_memory_store()
                        messages = await mem.load(session_id)

                        extra_perms = []
                        for item in resolved_hitls:
                            req = item.get("request", {})
                            resp = item.get("response", {})
                            tc_id = item.get("tool_call_id", "")

                            if req.get("type") == "tool_permission":
                                tool_name = req.get("tool_name", "")
                                tool_args = req.get("tool_args", {})

                                decision_val = resp.get("decision", "")
                                # Accept both legacy "approved" and structured option IDs
                                _APPROVE_DECISIONS = {
                                    "approved", "approve_once", "approve_session", "approve_permanent",
                                    "approve_session_narrow", "approve_permanent_narrow",
                                }
                                if decision_val in _APPROVE_DECISIONS:
                                    # Derive grant_scope from decision if not explicitly set
                                    _DECISION_TO_SCOPE = {
                                        "approve_once": "once",
                                        "approve_session": "session",
                                        "approve_session_narrow": "session",
                                        "approve_permanent": "permanent",
                                        "approve_permanent_narrow": "permanent",
                                        "approved": "once",
                                    }
                                    grant_scope = resp.get("grant_scope") or _DECISION_TO_SCOPE.get(decision_val, "once")

                                    # Use permission_pattern from resolution (e.g. "Bash(ls *)")
                                    # Falls back to bare tool_name for backward compatibility
                                    perm_pattern = resp.get("permission_pattern") or tool_name

                                    # Apply session grant so permission check passes
                                    # For "once" scope, grant the bare tool name (temporary)
                                    # For "session"/"permanent", grant the actual pattern
                                    grant_pat = tool_name if grant_scope == "once" else perm_pattern
                                    if hasattr(ctx.permissions, "add_session_grant"):
                                        ctx.permissions.add_session_grant(grant_pat)

                                    # Execute the tool through the pipeline — get real result
                                    try:
                                        tcc = ToolCallContext(
                                            tool_name=tool_name,
                                            args=tool_args,
                                            agent_context=ctx,
                                            tool_call_id=tc_id,
                                        )
                                        result = await ctx.tool_pipeline.execute(tcc)
                                        messages.append(Message(role="tool", content=result.content, tool_call_id=tc_id, created_at=datetime.now(timezone.utc).isoformat()))
                                    except Exception as exec_err:
                                        logger.warning("[session] tool execution failed after HITL approval: %s", exec_err)
                                        messages.append(Message(role="tool", content=f"Tool execution failed: {exec_err}", tool_call_id=tc_id, created_at=datetime.now(timezone.utc).isoformat()))

                                    # Remove temporary grant for "once" scope
                                    if grant_scope == "once":
                                        if hasattr(ctx.permissions, "_session_grants"):
                                            try:
                                                ctx.permissions._session_grants.remove(grant_pat)
                                            except ValueError:
                                                pass
                                    elif grant_scope in ("session", "permanent"):
                                        extra_perms.append(perm_pattern)

                                    if grant_scope == "permanent":
                                        try:
                                            from everstaff.permissions.definition_writer import YamlAgentDefinitionWriter
                                            writer = YamlAgentDefinitionWriter(agents_dir=str(agents_dir))
                                            await writer.add_allow_permission(
                                                agent_uuid or agent_name, perm_pattern,
                                                agent_path=agent_path,
                                            )
                                        except Exception as wr_err:
                                            logger.warning("Failed to write permanent grant for %s: %s", perm_pattern, wr_err)
                                else:
                                    # Rejected — inject error tool result
                                    messages.append(Message(
                                        role="tool",
                                        content=f"Permission denied: tool '{tool_name}' was rejected by the operator.",
                                        tool_call_id=tc_id,
                                        created_at=datetime.now(timezone.utc).isoformat(),
                                    ))
                            else:
                                # Non-tool_permission HITL: keep existing behavior
                                dtxt = _format_decision_message(req, resp.get("decision", ""), resp.get("comment"))
                                messages.append(Message(role="tool", content=dtxt, tool_call_id=tc_id, created_at=datetime.now(timezone.utc).isoformat()))

                        await mem.save(session_id, messages)
                        if extra_perms:
                            # Merge with existing session grants (additive)
                            existing = session_raw.get("extra_permissions", [])
                            merged = list(dict.fromkeys(existing + extra_perms))
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
    except HumanApprovalRequired:
        # HITL pause — runtime already wrote status="waiting_for_human".
        logger.info("[session] paused for HITL  agent=%s  session=%s", agent_name, _sid)
    except Exception as e:
        logger.error("[session] error agent=%s session=%s err=%s", agent_name, _sid, e)
        # Mark session as failed with error details so the UI shows why.
        try:
            _fail_meta = sessions_dir / session_id / "session.json"
            if _fail_meta.exists():
                _fail_data = json.loads(_fail_meta.read_text())
            else:
                _fail_data = {"session_id": session_id, "agent_name": agent_name}
            _fail_data["status"] = "failed"
            _fail_data["updated_at"] = datetime.now(timezone.utc).isoformat()
            _fail_data["error"] = f"{type(e).__name__}: {e}"
            _fail_meta.write_text(json.dumps(_fail_data, indent=2))
        except Exception:
            pass
    finally:
        if ctx is not None:
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
        # Robust fallback: if validation fails, at least try to preserve the system_prompt
        # if it's present and looks like a string.
        meta = SessionMetadata()
        if isinstance(raw_metadata, dict):
            sp = raw_metadata.get("system_prompt")
            if isinstance(sp, str):
                meta.system_prompt = sp
            if "title" in raw_metadata and isinstance(raw_metadata["title"], str):
                meta.title = raw_metadata["title"]
        return meta


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
        agent_uuid = body.agent_uuid or ""

        from everstaff.core.config import _builtin_agents_path as _bap
        from everstaff.utils.yaml_loader import load_yaml
        builtin_agents_dir = Path(_bap()) if _bap() else None

        agent_path = None

        # Try UUID-based lookup first: {uuid}.yaml
        if agent_uuid:
            candidate = (agents_dir_path / f"{agent_uuid}.yaml").resolve()
            if candidate.is_relative_to(agents_dir_path) and candidate.exists():
                agent_path = candidate
                if not agent_name:
                    agent_name = load_yaml(str(agent_path)).get("agent_name", "")

        # Scan by uuid inside YAML files
        if not agent_path and agent_uuid:
            for scan_dir in [agents_dir_path, builtin_agents_dir]:
                if not scan_dir or not scan_dir.exists():
                    continue
                for f in scan_dir.glob("*.yaml"):
                    try:
                        spec = load_yaml(str(f))
                        if spec.get("uuid") == agent_uuid:
                            agent_path = f
                            if not agent_name:
                                agent_name = spec.get("agent_name", "")
                            break
                    except Exception:
                        continue
                if agent_path:
                    break

        # Fall back to name-based lookup
        if not agent_path and agent_name:
            candidate = (agents_dir_path / f"{agent_name}.yaml").resolve()
            if candidate.is_relative_to(agents_dir_path) and candidate.exists():
                agent_path = candidate
            elif builtin_agents_dir and builtin_agents_dir.exists():
                # Scan builtins by agent_name inside YAML
                for f in builtin_agents_dir.glob("*.yaml"):
                    try:
                        spec = load_yaml(str(f))
                        if spec.get("agent_name") == agent_name:
                            agent_path = f
                            break
                    except Exception:
                        continue

        if not agent_path or not agent_path.exists():
            if not agent_name:
                raise HTTPException(status_code=400, detail="agent_name or valid agent_uuid is required")
            raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found")

        if not agent_name:
            agent_name = load_yaml(str(agent_path)).get("agent_name", "")
        if not agent_name:
            raise HTTPException(status_code=400, detail="agent_name or valid agent_uuid is required")

        session_id = str(uuid4())
        cm = getattr(request.app.state, "channel_manager", None)
        broadcast_fn = _extract_broadcast_fn(cm) if cm is not None else None
        mcp_pool = getattr(request.app.state, "mcp_pool", None)
        background_tasks.add_task(
            _resume_session_task, session_id, agent_name, body.user_input, config,
            broadcast_fn=broadcast_fn,
            channel_manager=cm,
            agent_uuid=agent_uuid,
            mcp_pool=mcp_pool,
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
                        error=raw.get("error"),
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
            error=raw.get("error"),
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
        # Update session status immediately so the UI sees "cancelled"
        # even before the runtime checks the cancel signal.
        session_path = f"{session_id}/session.json"
        try:
            raw = await store.read(session_path)
            session_data = json.loads(raw.decode())
            if session_data.get("status") == "running":
                session_data["status"] = "cancelled"
                await store.write(session_path, json.dumps(session_data, ensure_ascii=False).encode())
        except Exception:
            pass  # cancel.signal is the primary mechanism; this is best-effort
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
        agent_uuid = session_raw.get("agent_uuid", "")
        cm = getattr(request.app.state, "channel_manager", None)
        mcp_pool = getattr(request.app.state, "mcp_pool", None)

        # For cancelled/failed/interrupted: resume with optional user input
        if current_status in ("cancelled", "failed", "interrupted"):
            user_input = (body.user_input if body else "") or ""
            background_tasks.add_task(
                _resume_session_task, session_id, agent_name, user_input, config,
                broadcast_fn=_extract_broadcast_fn(cm) if cm is not None else None,
                channel_manager=cm,
                agent_uuid=agent_uuid,
                mcp_pool=mcp_pool,
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
            agent_uuid=agent_uuid,
            mcp_pool=mcp_pool,
        )
        return {"status": "resuming", "session_id": session_id}

    def _guard_workspace_path(session_id: str, subpath: str = "") -> Path:
        """Resolve workspace path and guard against traversal."""
        session_dir = _guard_session_id(sessions_dir, session_id)
        if not (session_dir / "session.json").exists():
            raise HTTPException(status_code=404, detail="Session not found")
        workspace = session_dir / "workspaces"
        if not subpath:
            return workspace
        target = (workspace / subpath).resolve()
        if not target.is_relative_to(workspace.resolve()):
            raise HTTPException(status_code=403, detail="Path traversal detected")
        return target

    @router.get("/sessions/{session_id}/files")
    async def list_files(
        session_id: str,
        path: str = Query(default=""),
    ) -> dict:
        from everstaff.schema.api_models import FileInfo, FileListResponse
        target = _guard_workspace_path(session_id, path)
        if not target.exists() or not target.is_dir():
            return FileListResponse(files=[], path=path).model_dump()
        files = []
        for entry in sorted(target.iterdir()):
            stat = entry.stat()
            files.append(FileInfo(
                name=entry.name,
                type="directory" if entry.is_dir() else "file",
                size=stat.st_size if entry.is_file() else 0,
                modified_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            ))
        return FileListResponse(files=files, path=path).model_dump()

    @router.get("/sessions/{session_id}/files/{file_path:path}")
    async def download_file(
        session_id: str,
        file_path: str,
        background_tasks: BackgroundTasks,
        download: bool = Query(default=False),
    ):
        from fastapi.responses import FileResponse
        import tempfile
        import shutil
        import os
        
        target = _guard_workspace_path(session_id, file_path)
        if not target.exists():
            raise HTTPException(status_code=404, detail="File not found")
        
        if target.is_dir():
            if not download:
                raise HTTPException(status_code=400, detail="Cannot preview a directory as a file")
            
            # Create a zip file
            tmp_fd, tmp_zip = tempfile.mkstemp(suffix=".zip")
            os.close(tmp_fd)
            base_name = tmp_zip[:-4] # make_archive appends .zip automatically
            shutil.make_archive(base_name, 'zip', str(target))
            
            def cleanup():
                try: os.remove(tmp_zip)
                except: pass
                
            background_tasks.add_task(cleanup)
            return FileResponse(
                path=tmp_zip,
                filename=f"{target.name}.zip",
                media_type="application/zip"
            )

        if download:
            return FileResponse(
                path=str(target),
                filename=target.name,
                media_type="application/octet-stream",
            )
        return FileResponse(path=str(target))

    return router

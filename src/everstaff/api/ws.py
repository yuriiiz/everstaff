"""WebSocket endpoint — unified channel for HITL events and runtime streaming."""
from __future__ import annotations

import asyncio
import json as _json
import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

# Note: these imports are at module level; if circular-import issues arise in
# future they can be moved back to deferred imports inside the handler.
from everstaff.api.hitl import _resolve_hitl_internal
from everstaff.api.sessions import _resume_session_task
from everstaff.channels.websocket import WebSocketChannel
from everstaff.session.index import SessionIndex

logger = logging.getLogger(__name__)


def make_router(config) -> APIRouter:
    router = APIRouter(tags=["websocket"])

    @router.websocket("/ws")
    async def ws_hitl(
        websocket: WebSocket,
        session_id: str | None = Query(default=None),
    ):
        """Unified WS channel.

        Client -> Server:
          {"type": "user_message", "content": "..."}
          {"type": "hitl_resolve", "hitl_id": "...", "decision": "...", "comment": "..."}

        Server -> Client:
          text_delta, tool_call_start, tool_call_end, session_end, hitl_request, hitl_resolved, error
        """
        await websocket.accept()
        app = websocket.app

        # --- WebSocket authentication ---
        auth_config = getattr(app.state.config, "auth", None)
        if auth_config is not None and auth_config.enabled:
            providers = app.state.auth_providers
            identity = None

            # 1. Try cookie/header auth via each provider directly (covers OIDC Code Flow)
            for provider in providers:
                try:
                    identity = await provider.authenticate(websocket)
                    if identity is not None:
                        break
                except Exception:
                    continue

            # 2. Fall back to ?token= query param (programmatic clients)
            if identity is None:
                token = websocket.query_params.get("token")
                if token:
                    from everstaff.api.auth.middleware import authenticate_token
                    identity = await authenticate_token(providers, token)

            if identity is None:
                await websocket.close(code=4001)
                return

            # Email whitelist check
            if auth_config.allowed_emails:
                allowed = {e.lower() for e in auth_config.allowed_emails}
                email = (identity.email or "").lower()
                if email not in allowed:
                    await websocket.close(code=4003)
                    return

            websocket.state.user = identity

        entry = (websocket, session_id)
        app.state.ws_connections.add(entry)
        _sid = (session_id or "")[:8] or "?"
        logger.info("[WS] connect  session=%s  active=%d", _sid, len(app.state.ws_connections))
        try:
            async for raw in websocket.iter_text():
                try:
                    msg = _json.loads(raw)
                except Exception:
                    continue
                msg_type = msg.get("type")

                # Look up broadcast fn once per message for both branches
                _broadcast_fn = None
                try:
                    for ch in app.state.channel_manager._channels:
                        if isinstance(ch, WebSocketChannel):
                            _broadcast_fn = ch._broadcast
                            break
                except Exception:
                    pass

                if msg_type == "user_message" and session_id:
                    content = msg.get("content", "")
                    client_id = msg.get("client_id", "")
                    logger.info("[WS] ← user_message  session=%s  chars=%d", _sid, len(content))

                    # Broadcast echo to all clients watching this session
                    if _broadcast_fn is not None:
                        try:
                            await _broadcast_fn({
                                "type": "user_message_echo",
                                "session_id": session_id,
                                "content": content,
                                "client_id": client_id,
                            })
                        except Exception as echo_err:
                            logger.debug("[WS] user_message_echo broadcast failed: %s", echo_err)

                    # Look up agent_name, agent_uuid, and session status from session file
                    agent_name = ""
                    agent_uuid = ""
                    _has_pending_hitl = False
                    _session_status = ""
                    _index = getattr(app.state, "session_index", None)
                    _ws_entry = _index.get(session_id) if _index else None
                    _ws_root = _ws_entry.root if _ws_entry and _ws_entry.root != session_id else None
                    try:
                        store = app.state.file_store
                        raw_bytes = await store.read(SessionIndex.session_relpath(session_id, _ws_root))
                        session_raw = _json.loads(raw_bytes)
                        agent_name = session_raw.get("agent_name", "")
                        agent_uuid = session_raw.get("agent_uuid", "")
                        _session_status = session_raw.get("status", "")
                        _has_pending_hitl = any(
                            r.get("status") == "pending"
                            for r in session_raw.get("hitl_requests", [])
                        )
                        logger.debug("[WS] resolved agent=%r uuid=%r status=%r pending_hitl=%s  session=%s",
                                     agent_name, agent_uuid, _session_status, _has_pending_hitl, _sid)
                    except Exception as e:
                        logger.warning("[WS] failed to read agent_name  session=%s  err=%s", _sid, e)

                    # Guard: don't resume a session that is waiting for HITL resolution.
                    # Sending a user_message while HITLs are pending would cause the
                    # runtime to drop dangling tool calls, silently auto-rejecting them.
                    if _session_status == "waiting_for_human" and _has_pending_hitl:
                        logger.warning("[WS] ignoring user_message for session %s: "
                                       "session is waiting_for_human with pending HITL(s)", _sid)
                        if _broadcast_fn is not None:
                            try:
                                await _broadcast_fn({
                                    "type": "error",
                                    "session_id": session_id,
                                    "error": "Cannot send message while HITL request is pending. "
                                             "Please resolve the pending request first.",
                                })
                            except Exception:
                                pass
                        continue

                    if not agent_name:
                        logger.warning("[WS] agent_name empty  session=%s  (resume may fail)", _sid)

                    # If the session is still running (e.g. stuck in a loop),
                    # write cancel.signal to stop it before starting a new resume.
                    # _resume_session_task will clear the signal before building
                    # the new runtime, so only the old runtime sees it.
                    if _session_status == "running":
                        try:
                            store = app.state.file_store
                            await store.write(
                                SessionIndex.signal_relpath(session_id, _ws_root),
                                _json.dumps({"force": False}).encode(),
                            )
                            logger.info("[WS] auto-stopping running session before resume  session=%s", _sid)
                            # Give the old runtime a moment to detect the signal
                            await asyncio.sleep(1)
                        except Exception as stop_err:
                            logger.warning("[WS] failed to auto-stop session %s: %s", _sid, stop_err)

                    cm = getattr(app.state, "channel_manager", None)
                    mcp_pool = getattr(app.state, "mcp_pool", None)
                    asyncio.create_task(
                        _resume_session_task(
                            session_id, agent_name, content, app.state.config,
                            broadcast_fn=_broadcast_fn,
                            channel_manager=cm,
                            agent_uuid=agent_uuid,
                            mcp_pool=mcp_pool,
                            root_session_id=_ws_root,
                            session_index=_index,
                        )
                    )

                elif msg_type == "hitl_resolve":
                    hitl_id = msg.get("hitl_id", "")
                    decision = msg.get("decision", "")
                    comment = msg.get("comment")
                    grant_scope = msg.get("grant_scope")
                    permission_pattern = msg.get("permission_pattern")
                    # Derive grant_scope from decision value if not provided explicitly
                    if not grant_scope and decision.startswith("approve_"):
                        grant_scope = decision.replace("approve_", "")  # approve_once→once, approve_session→session, approve_permanent→permanent
                    if hitl_id and decision:
                        logger.info("[WS] ← hitl_resolve  hitl=%s  decision=%s  pattern=%s  session=%s",
                                    hitl_id[:8], decision, permission_pattern, _sid)
                        asyncio.create_task(
                            _resolve_hitl_internal(app, hitl_id, decision, comment,
                                                   grant_scope=grant_scope,
                                                   permission_pattern=permission_pattern,
                                                   broadcast_fn=_broadcast_fn)
                        )

                elif msg_type:
                    logger.debug("[WS] ← unknown type=%r  session=%s", msg_type, _sid)

        except WebSocketDisconnect:
            pass
        finally:
            app.state.ws_connections.discard(entry)
            logger.info("[WS] disconnect  session=%s  active=%d", _sid, len(app.state.ws_connections))

    return router

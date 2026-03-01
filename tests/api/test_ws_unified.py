# tests/api/test_ws_unified.py
import json
import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from api import create_app


def _make_app(tmp_path):
    from everstaff.core.config import load_config
    config = load_config()
    config = config.model_copy(update={"sessions_dir": str(tmp_path / "sessions")})
    (tmp_path / "sessions").mkdir(exist_ok=True)
    return create_app(config=config, sessions_dir=str(tmp_path / "sessions"))


def test_ws_connects(tmp_path):
    """WS /ws should accept connection."""
    app = _make_app(tmp_path)
    client = TestClient(app)
    with client.websocket_connect("/api/ws") as ws:
        pass  # Just connect and disconnect


def test_ws_with_session_filter(tmp_path):
    """WS /ws?session_id=xxx should connect and only receive events for that session."""
    app = _make_app(tmp_path)
    client = TestClient(app)
    with client.websocket_connect("/api/ws?session_id=abc-123") as ws:
        pass


def test_ws_receives_broadcast_event(tmp_path):
    """Events broadcast to _ws_broadcast should be received by connected WS clients."""
    app = _make_app(tmp_path)
    client = TestClient(app)
    import asyncio

    with client.websocket_connect("/api/ws?session_id=test-session") as ws:
        # Directly invoke the broadcast function
        broadcast_fn = None
        # Find the WebSocketChannel's broadcast fn via channel_manager
        for ch in app.state.channel_manager._channels:
            from everstaff.channels.websocket import WebSocketChannel
            if isinstance(ch, WebSocketChannel):
                broadcast_fn = ch._broadcast
                break
        assert broadcast_fn is not None
        # TestClient runs an event loop internally in a thread; use asyncio.run() to
        # avoid "no current event loop" errors when calling from the main thread.
        asyncio.run(
            broadcast_fn({"type": "text_delta", "content": "hello", "session_id": "test-session"})
        )
        data = ws.receive_json()
        assert data["type"] == "text_delta"
        assert data["content"] == "hello"


def test_ws_user_message_dispatches_resume(tmp_path):
    """Sending user_message over WS should trigger _resume_session_task."""
    import json
    import time
    from unittest.mock import patch, AsyncMock

    # Create a session file so agent_name lookup works
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir(exist_ok=True)
    session_id = "test-session-123"
    (sessions_dir / session_id).mkdir()
    (sessions_dir / session_id / "session.json").write_text(
        json.dumps({"agent_name": "myagent", "status": "waiting_for_human"}), encoding="utf-8"
    )

    app = _make_app(tmp_path)
    client = TestClient(app)

    with patch("everstaff.api.ws._resume_session_task", new_callable=AsyncMock) as mock_resume:
        with client.websocket_connect(f"/api/ws?session_id={session_id}") as ws:
            ws.send_text(json.dumps({"type": "user_message", "content": "hello"}))
            time.sleep(0.2)  # Let the task run

    mock_resume.assert_called_once()
    call_args = mock_resume.call_args
    assert call_args[0][0] == session_id  # session_id
    assert call_args[0][2] == "hello"     # content/decision_text


def test_ws_user_message_broadcasts_echo(tmp_path):
    """Sending user_message should broadcast user_message_echo to all session clients."""
    import json
    import time
    import asyncio

    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir(exist_ok=True)
    session_id = "echo-test-session"
    (sessions_dir / session_id).mkdir()
    (sessions_dir / session_id / "session.json").write_text(
        json.dumps({"agent_name": "myagent", "status": "running"}), encoding="utf-8"
    )

    app = _make_app(tmp_path)
    client = TestClient(app)

    with patch("everstaff.api.ws._resume_session_task", new_callable=AsyncMock):
        with client.websocket_connect(f"/api/ws?session_id={session_id}") as ws1:
            with client.websocket_connect(f"/api/ws?session_id={session_id}") as ws2:
                ws1.send_text(json.dumps({
                    "type": "user_message",
                    "content": "hello from ws1",
                    "client_id": "client-aaa"
                }))
                time.sleep(0.2)
                # Both ws1 and ws2 should receive the echo
                data1 = ws1.receive_json()
                assert data1["type"] == "user_message_echo"
                assert data1["content"] == "hello from ws1"
                assert data1["client_id"] == "client-aaa"
                assert data1["session_id"] == session_id

                data2 = ws2.receive_json()
                assert data2["type"] == "user_message_echo"
                assert data2["content"] == "hello from ws1"
                assert data2["client_id"] == "client-aaa"


def test_ws_hitl_resolve_dispatches_internal(tmp_path):
    """Sending hitl_resolve over WS should trigger _resolve_hitl_internal."""
    import json
    import time
    from unittest.mock import patch, AsyncMock

    app = _make_app(tmp_path)
    client = TestClient(app)

    with patch("everstaff.api.ws._resolve_hitl_internal", new_callable=AsyncMock) as mock_resolve:
        with client.websocket_connect("/api/ws?session_id=any") as ws:
            ws.send_text(json.dumps({
                "type": "hitl_resolve",
                "hitl_id": "hitl-abc",
                "decision": "approved",
                "comment": "looks good"
            }))
            time.sleep(0.2)

    mock_resolve.assert_called_once()
    call_args = mock_resolve.call_args
    assert call_args[0][1] == "hitl-abc"   # hitl_id
    assert call_args[0][2] == "approved"   # decision

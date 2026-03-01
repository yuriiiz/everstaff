"""Tests for the HITL-push WebSocket endpoint."""
import pytest
from starlette.testclient import TestClient
from everstaff.api import create_app


def test_ws_endpoint_exists(tmp_path):
    """The /ws endpoint should exist and accept WebSocket connections."""
    app = create_app(sessions_dir=str(tmp_path))
    client = TestClient(app)
    with client.websocket_connect("/api/ws") as ws:
        # Connection accepted — endpoint exists
        pass


def test_ws_session_filter_endpoint_exists(tmp_path):
    """The /ws?session_id= filter endpoint should work."""
    app = create_app(sessions_dir=str(tmp_path))
    client = TestClient(app)
    with client.websocket_connect("/api/ws?session_id=test-session") as ws:
        pass


def test_ws_connections_uses_tuple_format(tmp_path):
    """ws_connections should store (websocket, session_filter) tuples."""
    app = create_app(sessions_dir=str(tmp_path))
    client = TestClient(app)
    with client.websocket_connect("/api/ws") as ws:
        # During connection, ws_connections should contain tuples
        conns = list(app.state.ws_connections)
        assert len(conns) == 1
        assert isinstance(conns[0], tuple)
        assert len(conns[0]) == 2
        # Second element is None for no filter
        assert conns[0][1] is None


def test_ws_session_filter_stored(tmp_path):
    """Session filter should be stored in ws_connections tuple."""
    app = create_app(sessions_dir=str(tmp_path))
    client = TestClient(app)
    with client.websocket_connect("/api/ws?session_id=my-session") as ws:
        conns = list(app.state.ws_connections)
        assert len(conns) == 1
        assert conns[0][1] == "my-session"

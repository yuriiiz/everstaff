"""Tests for session workspace file API endpoints."""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _write_session(sessions_dir: Path, session_id: str) -> None:
    d = sessions_dir / session_id
    d.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    (d / "session.json").write_text(json.dumps({
        "session_id": session_id,
        "agent_name": "test-agent",
        "parent_session_id": None,
        "created_at": now,
        "updated_at": now,
        "status": "completed",
        "metadata": {},
        "messages": [],
    }))


@pytest.fixture
def sessions_dir(tmp_path):
    d = tmp_path / "sessions"
    d.mkdir()
    return d


@pytest.fixture
def client(sessions_dir):
    from everstaff.api import create_app
    app = create_app(sessions_dir=str(sessions_dir))
    return TestClient(app)


def test_file_info_model():
    from everstaff.schema.api_models import FileInfo
    info = FileInfo(name="report.csv", type="file", size=1024, modified_at="2026-03-04T10:00:00")
    assert info.name == "report.csv"
    assert info.type == "file"


def test_file_list_response_model():
    from everstaff.schema.api_models import FileListResponse, FileInfo
    resp = FileListResponse(
        files=[FileInfo(name="a.txt", type="file", size=10, modified_at="2026-03-04T10:00:00")],
        path="",
    )
    assert len(resp.files) == 1


def test_list_files_empty_workspace(client, sessions_dir):
    """GET /sessions/{id}/files returns empty list when workspace has no files."""
    _write_session(sessions_dir, "sess-1")
    (sessions_dir / "sess-1" / "workspaces").mkdir(parents=True, exist_ok=True)
    resp = client.get("/api/sessions/sess-1/files")
    assert resp.status_code == 200
    data = resp.json()
    assert data["files"] == []
    assert data["path"] == ""


def test_list_files_with_files(client, sessions_dir):
    """GET /sessions/{id}/files returns file metadata."""
    _write_session(sessions_dir, "sess-2")
    ws = sessions_dir / "sess-2" / "workspaces"
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "report.csv").write_text("a,b,c")
    (ws / "subdir").mkdir()
    resp = client.get("/api/sessions/sess-2/files")
    assert resp.status_code == 200
    data = resp.json()
    names = {f["name"] for f in data["files"]}
    assert "report.csv" in names
    assert "subdir" in names
    by_name = {f["name"]: f for f in data["files"]}
    assert by_name["report.csv"]["type"] == "file"
    assert by_name["report.csv"]["size"] == 5
    assert by_name["subdir"]["type"] == "directory"


def test_list_files_subdir(client, sessions_dir):
    """GET /sessions/{id}/files?path=subdir lists files within subdir."""
    _write_session(sessions_dir, "sess-3")
    ws = sessions_dir / "sess-3" / "workspaces"
    sub = ws / "output"
    sub.mkdir(parents=True, exist_ok=True)
    (sub / "result.json").write_text("{}")
    resp = client.get("/api/sessions/sess-3/files?path=output")
    assert resp.status_code == 200
    data = resp.json()
    assert data["path"] == "output"
    assert any(f["name"] == "result.json" for f in data["files"])


def test_list_files_session_not_found(client):
    """GET /sessions/{id}/files returns 404 for unknown session."""
    resp = client.get("/api/sessions/nonexistent/files")
    assert resp.status_code == 404


def test_list_files_no_workspace_dir(client, sessions_dir):
    """GET /sessions/{id}/files returns empty list when workspaces dir doesn't exist."""
    _write_session(sessions_dir, "sess-no-ws")
    resp = client.get("/api/sessions/sess-no-ws/files")
    assert resp.status_code == 200
    assert resp.json()["files"] == []


def test_list_files_path_traversal(client, sessions_dir):
    """GET /sessions/{id}/files?path=../../ etc is blocked."""
    _write_session(sessions_dir, "sess-traversal")
    (sessions_dir / "sess-traversal" / "workspaces").mkdir(parents=True, exist_ok=True)
    resp = client.get("/api/sessions/sess-traversal/files?path=../../")
    assert resp.status_code == 403

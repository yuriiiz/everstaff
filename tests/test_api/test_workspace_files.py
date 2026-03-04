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

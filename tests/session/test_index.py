"""Tests for SessionIndex."""
import json
import pytest
from pathlib import Path

from everstaff.session.index import IndexEntry, SessionIndex


@pytest.fixture
def sessions_dir(tmp_path):
    return tmp_path / "sessions"


@pytest.fixture
def index(sessions_dir):
    sessions_dir.mkdir()
    return SessionIndex(sessions_dir)


class TestSessionRelpath:
    def test_root_session(self):
        assert SessionIndex.session_relpath("abc", None) == "abc/session.json"
        assert SessionIndex.session_relpath("abc", "abc") == "abc/session.json"

    def test_child_session(self):
        assert SessionIndex.session_relpath("child", "root") == "root/sub_sessions/child.json"


class TestSignalRelpath:
    def test_root(self):
        assert SessionIndex.signal_relpath("abc", None) == "abc/cancel.signal"

    def test_child_uses_root(self):
        assert SessionIndex.signal_relpath("child", "root") == "root/cancel.signal"


class TestUpsertAndGet:
    def test_upsert_and_get(self, index):
        entry = IndexEntry(id="s1", root="s1", agent="test-agent", status="running",
                           created_at="2025-01-01T00:00:00Z", updated_at="2025-01-01T00:00:00Z")
        index.upsert(entry)
        assert index.get("s1") == entry
        assert index.get("nonexistent") is None

    def test_upsert_overwrites(self, index):
        e1 = IndexEntry(id="s1", root="s1", status="running", created_at="2025-01-01T00:00:00Z")
        e2 = IndexEntry(id="s1", root="s1", status="completed", created_at="2025-01-01T00:00:00Z")
        index.upsert(e1)
        index.upsert(e2)
        assert index.get("s1").status == "completed"


class TestPersistence:
    def test_survives_reload(self, sessions_dir):
        sessions_dir.mkdir()
        idx1 = SessionIndex(sessions_dir)
        idx1.upsert(IndexEntry(id="s1", root="s1", agent="a", status="running",
                                created_at="2025-01-01T00:00:00Z"))
        idx1.upsert(IndexEntry(id="s2", root="s1", parent="s1", agent="b", status="running",
                                created_at="2025-01-02T00:00:00Z"))
        # Reload from disk
        idx2 = SessionIndex(sessions_dir)
        assert idx2.get("s1") is not None
        assert idx2.get("s2") is not None
        assert idx2.get("s2").parent == "s1"


class TestListRoots:
    def test_only_roots(self, index):
        index.upsert(IndexEntry(id="r1", root="r1", status="running", created_at="2025-01-01T00:00:00Z"))
        index.upsert(IndexEntry(id="c1", root="r1", parent="r1", status="running", created_at="2025-01-02T00:00:00Z"))
        index.upsert(IndexEntry(id="r2", root="r2", status="completed", created_at="2025-01-03T00:00:00Z"))

        roots = index.list_roots()
        root_ids = [e.id for e in roots]
        assert "r1" in root_ids
        assert "r2" in root_ids
        assert "c1" not in root_ids

    def test_filter_status(self, index):
        index.upsert(IndexEntry(id="r1", root="r1", status="running", created_at="2025-01-01T00:00:00Z"))
        index.upsert(IndexEntry(id="r2", root="r2", status="completed", created_at="2025-01-02T00:00:00Z"))
        roots = index.list_roots(status="completed")
        assert len(roots) == 1
        assert roots[0].id == "r2"

    def test_filter_agent_uuid(self, index):
        index.upsert(IndexEntry(id="r1", root="r1", agent_uuid="uuid-a", created_at="2025-01-01T00:00:00Z"))
        index.upsert(IndexEntry(id="r2", root="r2", agent_uuid="uuid-b", created_at="2025-01-02T00:00:00Z"))
        roots = index.list_roots(agent_uuid="uuid-a")
        assert len(roots) == 1
        assert roots[0].id == "r1"

    def test_pagination(self, index):
        for i in range(5):
            index.upsert(IndexEntry(id=f"r{i}", root=f"r{i}", created_at=f"2025-01-0{i+1}T00:00:00Z"))
        page = index.list_roots(limit=2, offset=0)
        assert len(page) == 2
        # newest first
        assert page[0].id == "r4"


class TestChildrenOf:
    def test_returns_children(self, index):
        index.upsert(IndexEntry(id="r1", root="r1", created_at="2025-01-01T00:00:00Z"))
        index.upsert(IndexEntry(id="c1", root="r1", parent="r1", created_at="2025-01-02T00:00:00Z"))
        index.upsert(IndexEntry(id="c2", root="r1", parent="c1", created_at="2025-01-03T00:00:00Z"))
        children = index.children_of("r1")
        child_ids = {e.id for e in children}
        assert child_ids == {"c1", "c2"}


class TestRootOf:
    def test_known(self, index):
        index.upsert(IndexEntry(id="c1", root="r1", parent="r1", created_at="2025-01-01T00:00:00Z"))
        assert index.root_of("c1") == "r1"

    def test_unknown(self, index):
        assert index.root_of("nonexistent") is None


class TestRemove:
    def test_remove(self, index):
        index.upsert(IndexEntry(id="s1", root="s1", created_at="2025-01-01T00:00:00Z"))
        index.remove("s1")
        assert index.get("s1") is None
        # Also removed from file
        idx2 = SessionIndex(index._dir)
        assert idx2.get("s1") is None


class TestCompact:
    def test_removes_duplicates(self, sessions_dir):
        sessions_dir.mkdir()
        idx = SessionIndex(sessions_dir)
        # Write same entry 3 times
        for status in ["running", "waiting", "completed"]:
            idx.upsert(IndexEntry(id="s1", root="s1", status=status, created_at="2025-01-01T00:00:00Z"))
        # File has 3 lines
        lines_before = (sessions_dir / "_index.jsonl").read_text().strip().splitlines()
        assert len(lines_before) == 3
        idx.compact()
        lines_after = (sessions_dir / "_index.jsonl").read_text().strip().splitlines()
        assert len(lines_after) == 1
        assert json.loads(lines_after[0])["status"] == "completed"


class TestRebuild:
    def test_rebuild_from_filesystem(self, sessions_dir):
        sessions_dir.mkdir()
        # Create a root session
        root_dir = sessions_dir / "root-1"
        root_dir.mkdir()
        (root_dir / "session.json").write_text(json.dumps({
            "session_id": "root-1",
            "agent_name": "main",
            "status": "completed",
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T01:00:00Z",
        }))
        # Create a child session
        sub_dir = root_dir / "sub_sessions"
        sub_dir.mkdir()
        (sub_dir / "child-1.json").write_text(json.dumps({
            "session_id": "child-1",
            "parent_session_id": "root-1",
            "root_session_id": "root-1",
            "agent_name": "worker",
            "status": "completed",
            "created_at": "2025-01-01T00:30:00Z",
            "updated_at": "2025-01-01T01:00:00Z",
        }))
        idx = SessionIndex(sessions_dir)
        idx.rebuild()
        assert idx.get("root-1") is not None
        assert idx.get("root-1").agent == "main"
        assert idx.get("child-1") is not None
        assert idx.get("child-1").root == "root-1"
        assert idx.get("child-1").parent == "root-1"

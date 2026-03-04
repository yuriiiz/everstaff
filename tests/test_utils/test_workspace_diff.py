import os
import pytest
from pathlib import Path


def test_snapshot_empty_dir(tmp_path):
    from everstaff.utils.workspace_diff import snapshot_workspace
    result = snapshot_workspace(tmp_path)
    assert result == {}


def test_snapshot_captures_files(tmp_path):
    from everstaff.utils.workspace_diff import snapshot_workspace
    (tmp_path / "a.txt").write_text("hello")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.py").write_text("x = 1")
    result = snapshot_workspace(tmp_path)
    assert "a.txt" in result
    assert "sub/b.py" in result
    assert result["a.txt"][0] == 5  # size
    assert result["sub/b.py"][0] == 5


def test_diff_detects_new_file(tmp_path):
    from everstaff.utils.workspace_diff import snapshot_workspace, diff_snapshots
    before = snapshot_workspace(tmp_path)
    (tmp_path / "new.txt").write_text("new content")
    after = snapshot_workspace(tmp_path)
    created, modified = diff_snapshots(before, after)
    assert "new.txt" in created
    assert len(modified) == 0


def test_diff_detects_modified_file(tmp_path):
    from everstaff.utils.workspace_diff import snapshot_workspace, diff_snapshots
    (tmp_path / "exist.txt").write_text("old")
    before = snapshot_workspace(tmp_path)
    (tmp_path / "exist.txt").write_text("new content longer")
    after = snapshot_workspace(tmp_path)
    created, modified = diff_snapshots(before, after)
    assert len(created) == 0
    assert "exist.txt" in modified


def test_diff_ignores_unchanged(tmp_path):
    from everstaff.utils.workspace_diff import snapshot_workspace, diff_snapshots
    (tmp_path / "stable.txt").write_text("no change")
    before = snapshot_workspace(tmp_path)
    after = snapshot_workspace(tmp_path)
    created, modified = diff_snapshots(before, after)
    assert len(created) == 0
    assert len(modified) == 0


def test_snapshot_nonexistent_dir(tmp_path):
    from everstaff.utils.workspace_diff import snapshot_workspace
    result = snapshot_workspace(tmp_path / "nope")
    assert result == {}


def test_guess_mime():
    from everstaff.utils.workspace_diff import guess_mime
    assert guess_mime("report.md") == "text/markdown"
    assert guess_mime("image.png") == "image/png"
    assert guess_mime("video.mp4") == "video/mp4"
    assert guess_mime("data.json") == "application/json"
    assert guess_mime("page.html") == "text/html"
    assert guess_mime("noext") == "application/octet-stream"

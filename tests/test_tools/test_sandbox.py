"""Tests for session-scoped file sandbox — path safety + tool factories."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest


def test_resolve_safe_path_rejects_absolute():
    from everstaff.tools.path_utils import resolve_safe_path
    workdir = Path("/tmp/workspace")
    with pytest.raises(ValueError, match="Absolute paths not allowed"):
        resolve_safe_path(workdir, "/etc/passwd")


def test_resolve_safe_path_rejects_traversal():
    from everstaff.tools.path_utils import resolve_safe_path
    workdir = Path("/tmp/workspace")
    with pytest.raises(ValueError, match="Path traversal not allowed"):
        resolve_safe_path(workdir, "../../etc/passwd")


def test_resolve_safe_path_accepts_relative(tmp_path):
    from everstaff.tools.path_utils import resolve_safe_path
    result = resolve_safe_path(tmp_path, "subdir/file.txt")
    assert result == tmp_path / "subdir" / "file.txt"


def test_resolve_safe_path_accepts_simple_name(tmp_path):
    from everstaff.tools.path_utils import resolve_safe_path
    result = resolve_safe_path(tmp_path, "file.txt")
    assert result == tmp_path / "file.txt"


def test_read_tool_rejects_absolute(tmp_path):
    from everstaff.tools.read import make_read_tool
    t = make_read_tool(tmp_path)
    result = asyncio.run(t.execute({"file_path": "/etc/passwd"}))
    assert "Error" in result
    assert "Absolute" in result


def test_write_tool_rejects_traversal(tmp_path):
    from everstaff.tools.write import make_write_tool
    t = make_write_tool(tmp_path)
    result = asyncio.run(t.execute({"file_path": "../../evil.txt", "content": "bad"}))
    assert "Error" in result


def test_write_then_read_within_workdir(tmp_path):
    from everstaff.tools.write import make_write_tool
    from everstaff.tools.read import make_read_tool

    write_tool = make_write_tool(tmp_path)
    read_tool = make_read_tool(tmp_path)

    r = asyncio.run(write_tool.execute({"file_path": "hello.txt", "content": "hello world"}))
    assert "Successfully" in r

    r2 = asyncio.run(read_tool.execute({"file_path": "hello.txt"}))
    assert "hello world" in r2


def test_working_dir_cli_creates_per_session_dir(tmp_path):
    from everstaff.builder.environment import CLIEnvironment
    env = CLIEnvironment(sessions_dir=str(tmp_path / "sessions"))
    workdir = env.working_dir("test-session-123")
    assert workdir.exists()
    assert "test-session-123" in str(workdir)


def test_working_dir_test_environment_returns_temp_dir():
    from everstaff.builder.environment import TestEnvironment
    env = TestEnvironment()
    workdir = env.working_dir("any-session")
    assert workdir.exists()

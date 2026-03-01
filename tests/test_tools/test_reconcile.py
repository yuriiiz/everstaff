import pytest
import time
from pathlib import Path
from unittest.mock import MagicMock


def _make_env(sessions_dir=None, project_root=None):
    env = MagicMock()
    env.sessions_dir = MagicMock(return_value=sessions_dir)
    env.project_root = MagicMock(return_value=project_root or Path.cwd())
    return env


@pytest.mark.asyncio
async def test_archive_sessions(tmp_path):
    """archive_sessions compresses old sessions and removes originals."""
    from everstaff.tools.reconcile import SystemReconcileTool

    sessions = tmp_path / "sessions"
    sessions.mkdir()

    # Create an old session (set mtime to 10 days ago)
    old_session = sessions / "old-sess"
    old_session.mkdir()
    (old_session / "messages.json").write_text("[]")
    old_time = time.time() - 86400 * 10
    import os
    os.utime(old_session, (old_time, old_time))

    # Create a recent session
    new_session = sessions / "new-sess"
    new_session.mkdir()
    (new_session / "messages.json").write_text("[]")

    env = _make_env(sessions_dir=str(sessions), project_root=tmp_path)
    tool = SystemReconcileTool(env)
    result = await tool.execute({"action": "archive_sessions", "retention_days": 7})

    assert result.is_error is False
    assert "1" in result.content  # archived 1 session
    assert "old-sess" in result.content

    # Old session archived
    archive = tmp_path / "archive" / "sessions" / "old-sess.tar.gz"
    assert archive.exists()
    assert not old_session.exists()

    # New session untouched
    assert new_session.exists()


@pytest.mark.asyncio
async def test_cleanup_memory(tmp_path):
    """cleanup_memory removes old memory files."""
    from everstaff.tools.reconcile import SystemReconcileTool

    memory_dir = tmp_path / ".agent" / "memory"
    memory_dir.mkdir(parents=True)

    old_file = memory_dir / "old_context.md"
    old_file.write_text("stale data")
    old_time = time.time() - 86400 * 10
    import os
    os.utime(old_file, (old_time, old_time))

    new_file = memory_dir / "recent.md"
    new_file.write_text("fresh data")

    env = _make_env(project_root=tmp_path)
    tool = SystemReconcileTool(env)
    result = await tool.execute({"action": "cleanup_memory", "retention_days": 7})

    assert result.is_error is False
    assert not old_file.exists()
    assert new_file.exists()


@pytest.mark.asyncio
async def test_cleanup_logs(tmp_path):
    """cleanup_logs removes old log files from .agent/logs and .agent/traces."""
    from everstaff.tools.reconcile import SystemReconcileTool

    logs_dir = tmp_path / ".agent" / "logs"
    logs_dir.mkdir(parents=True)

    old_log = logs_dir / "2026-02-20.log"
    old_log.write_text("old log")
    old_time = time.time() - 86400 * 10
    import os
    os.utime(old_log, (old_time, old_time))

    new_log = logs_dir / "2026-03-01.log"
    new_log.write_text("today's log")

    env = _make_env(project_root=tmp_path)
    tool = SystemReconcileTool(env)
    result = await tool.execute({"action": "cleanup_logs", "retention_days": 7})

    assert result.is_error is False
    assert not old_log.exists()
    assert new_log.exists()


@pytest.mark.asyncio
async def test_cleanup_temp(tmp_path):
    """cleanup_temp removes old temp files from .agent/cache and .agent/tmp."""
    from everstaff.tools.reconcile import SystemReconcileTool

    cache_dir = tmp_path / ".agent" / "cache"
    cache_dir.mkdir(parents=True)

    old_cache = cache_dir / "old_data.bin"
    old_cache.write_text("stale")
    old_time = time.time() - 86400 * 10
    import os
    os.utime(old_cache, (old_time, old_time))

    new_cache = cache_dir / "fresh.bin"
    new_cache.write_text("fresh")

    env = _make_env(project_root=tmp_path)
    tool = SystemReconcileTool(env)
    result = await tool.execute({"action": "cleanup_temp", "retention_days": 7})

    assert result.is_error is False
    assert not old_cache.exists()
    assert new_cache.exists()


@pytest.mark.asyncio
async def test_unknown_action():
    """Unknown action returns error."""
    from everstaff.tools.reconcile import SystemReconcileTool

    env = _make_env()
    tool = SystemReconcileTool(env)
    result = await tool.execute({"action": "invalid_action"})

    assert result.is_error is True
    assert "Unknown action" in result.content


@pytest.mark.asyncio
async def test_no_sessions_dir():
    """archive_sessions with no sessions_dir configured returns graceful message."""
    from everstaff.tools.reconcile import SystemReconcileTool

    env = _make_env(sessions_dir=None)
    tool = SystemReconcileTool(env)
    result = await tool.execute({"action": "archive_sessions"})

    assert result.is_error is False
    assert "No sessions directory" in result.content

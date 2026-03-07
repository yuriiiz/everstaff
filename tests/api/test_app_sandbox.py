from unittest.mock import patch

import pytest
from everstaff.api import create_app
from everstaff.core.config import FrameworkConfig, SandboxConfig


@patch("everstaff.mcp_client.pool.McpConnectionPool.start_cleanup_loop")
def test_executor_manager_created_when_sandbox_enabled(mock_cleanup, tmp_path):
    """create_app creates ExecutorManager when sandbox.enabled=True."""
    config = FrameworkConfig(sandbox=SandboxConfig(enabled=True, type="process"))
    app = create_app(config=config, sessions_dir=str(tmp_path / "sessions"))
    assert hasattr(app.state, "executor_manager")
    assert app.state.executor_manager is not None


@patch("everstaff.mcp_client.pool.McpConnectionPool.start_cleanup_loop")
def test_no_executor_manager_when_sandbox_disabled(mock_cleanup, tmp_path):
    """create_app does NOT create ExecutorManager when sandbox.enabled=False."""
    config = FrameworkConfig(sandbox=SandboxConfig(enabled=False))
    app = create_app(config=config, sessions_dir=str(tmp_path / "sessions"))
    assert getattr(app.state, "executor_manager", None) is None

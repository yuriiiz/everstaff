import pytest
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path
from everstaff.api.sessions import _resume_session_task


@pytest.mark.asyncio
async def test_resume_session_sandbox_path(tmp_path):
    """When config.sandbox.enabled, _resume_session_task uses ExecutorManager."""
    from everstaff.core.config import FrameworkConfig, SandboxConfig

    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    (agents_dir / "test-agent.yaml").write_text(
        "agent_name: test-agent\nuuid: agent-uuid-1\n"
    )
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()

    config = FrameworkConfig(
        agents_dir=str(agents_dir),
        sessions_dir=str(sessions_dir),
        sandbox=SandboxConfig(enabled=True, type="process"),
    )

    mock_executor = AsyncMock()
    mock_executor.is_alive = True
    mock_executor.wait_finished = AsyncMock(return_value=0)
    mock_executor.spawn_agent = AsyncMock()
    mock_executor._ipc_handler = MagicMock()

    mock_mgr = AsyncMock()
    mock_mgr.get_or_create = AsyncMock(return_value=mock_executor)
    mock_mgr.destroy = AsyncMock()

    events_received = []
    async def mock_broadcast(event):
        events_received.append(event)

    await _resume_session_task(
        session_id="test-sid",
        agent_name="test-agent",
        decision_text="hello",
        config=config,
        broadcast_fn=mock_broadcast,
        executor_manager=mock_mgr,
    )

    mock_mgr.get_or_create.assert_called_once_with("test-sid")
    mock_executor.spawn_agent.assert_called_once()
    mock_executor.wait_finished.assert_called_once()
    mock_mgr.destroy.assert_called_once_with("test-sid")


@pytest.mark.asyncio
async def test_resume_session_inprocess_when_no_sandbox(tmp_path):
    """When sandbox disabled, _resume_session_task uses in-process path."""
    from everstaff.core.config import FrameworkConfig, SandboxConfig

    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    (agents_dir / "test-agent.yaml").write_text(
        "agent_name: test-agent\nuuid: agent-uuid-1\n"
    )
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()

    config = FrameworkConfig(
        agents_dir=str(agents_dir),
        sessions_dir=str(sessions_dir),
        sandbox=SandboxConfig(enabled=False),
    )

    # When sandbox disabled, it should go through the in-process path
    # which will try to build AgentBuilder — we can just verify it doesn't
    # call executor_manager
    mock_mgr = AsyncMock()

    with patch("everstaff.builder.agent_builder.AgentBuilder") as MockBuilder:
        mock_runtime = AsyncMock()
        async def empty_stream(*a, **kw):
            return
            yield  # make it an async generator
        mock_runtime.run_stream = empty_stream
        mock_ctx = AsyncMock()
        MockBuilder.return_value.build = AsyncMock(return_value=(mock_runtime, mock_ctx))

        await _resume_session_task(
            session_id="test-sid",
            agent_name="test-agent",
            decision_text="hello",
            config=config,
            executor_manager=mock_mgr,
        )

    mock_mgr.get_or_create.assert_not_called()

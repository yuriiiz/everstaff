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


@pytest.mark.asyncio
async def test_stop_session_pushes_cancel_to_sandbox(tmp_path):
    """POST /sessions/{id}/stop pushes cancel to active sandbox executor."""
    from httpx import AsyncClient, ASGITransport
    from everstaff.api import create_app
    from everstaff.core.config import FrameworkConfig, SandboxConfig

    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    sid = "test-stop-sid-00000000-0000-0000-0000-000000000000"
    (sessions_dir / sid).mkdir()
    (sessions_dir / sid / "session.json").write_text(json.dumps({
        "session_id": sid, "status": "running", "agent_name": "a",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }))

    config = FrameworkConfig(
        sessions_dir=str(sessions_dir),
        sandbox=SandboxConfig(enabled=True, type="process"),
    )
    app = create_app(config=config, sessions_dir=str(sessions_dir))

    mock_executor = AsyncMock()
    mock_mgr = MagicMock()
    mock_mgr.has_active = MagicMock(return_value=True)
    mock_mgr._executors = {sid: mock_executor}
    app.state.executor_manager = mock_mgr

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(f"/api/sessions/{sid}/stop")

    assert resp.status_code == 200
    mock_executor.push_cancel.assert_called_once()


@pytest.mark.asyncio
async def test_resolve_hitl_pushes_to_sandbox(tmp_path):
    """_resolve_hitl_internal pushes HITL resolution to active sandbox executor."""
    from everstaff.api.hitl import _resolve_hitl_internal

    # Set up a mock app with all needed state
    app = MagicMock()
    store = AsyncMock()

    sid = "hitl-sandbox-sid"
    hitl_id = "hitl-001"

    session_data = {
        "session_id": sid,
        "status": "waiting_for_human",
        "agent_name": "a",
        "agent_uuid": "a-uuid",
        "hitl_requests": [
            {"hitl_id": hitl_id, "status": "pending", "prompt": "approve?"},
        ],
    }

    # store.read returns session data; store.list returns paths
    async def mock_read(path):
        return json.dumps(session_data).encode()

    store.read = AsyncMock(side_effect=mock_read)
    store.list = AsyncMock(return_value=[f"{sid}/session.json"])
    store.write = AsyncMock()

    app.state.file_store = store
    app.state.config = MagicMock()
    app.state.channel_manager = None

    # Set up session index mock
    mock_index = MagicMock()
    mock_entry = MagicMock()
    mock_entry.id = sid
    mock_entry.root = sid
    mock_entry.status = "waiting_for_human"
    mock_entry.agent = "a"
    mock_index.get = MagicMock(return_value=mock_entry)
    mock_index._entries = {sid: mock_entry}
    app.state.session_index = mock_index

    # Set up executor manager
    mock_executor = AsyncMock()
    mock_mgr = MagicMock()
    mock_mgr.has_active = MagicMock(return_value=True)
    mock_mgr._executors = {sid: mock_executor}
    app.state.executor_manager = mock_mgr

    with patch("everstaff.api.hitl.canonical_resolve", new_callable=AsyncMock), \
         patch("everstaff.api.hitl.all_hitls_settled", return_value=False):
        await _resolve_hitl_internal(app, hitl_id, "approved", comment="ok")

    mock_executor.push_hitl_resolution.assert_called_once_with(hitl_id, "approved", "ok")

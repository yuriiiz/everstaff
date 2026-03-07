"""Tests for sandbox entry point."""
import asyncio
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from everstaff.sandbox.entry import sandbox_main, parse_args, _run_agent


class TestParseArgs:
    def test_parse_args_basic(self):
        args = parse_args(["--socket-path", "/tmp/test.sock", "--token", "abc123",
                           "--session-id", "s1", "--agent-spec", '{"name":"test"}'])
        assert args.socket_path == "/tmp/test.sock"
        assert args.token == "abc123"
        assert args.session_id == "s1"
        assert args.agent_spec == '{"name":"test"}'

    def test_parse_args_with_workspace(self):
        args = parse_args(["--socket-path", "/tmp/test.sock", "--token", "abc",
                           "--session-id", "s1", "--agent-spec", "{}",
                           "--workspace-dir", "/work"])
        assert args.workspace_dir == "/work"


@pytest.mark.asyncio
class TestSandboxMain:
    async def test_connects_and_authenticates(self, tmp_path):
        """sandbox_main should connect to IPC, authenticate, get secrets."""
        mock_channel = MagicMock()
        mock_channel.connect = AsyncMock()
        mock_channel.send_request = AsyncMock(return_value={
            "secrets": {"API_KEY": "secret123"},
        })
        mock_channel.on_push = MagicMock()
        mock_channel.close = AsyncMock()

        with patch("everstaff.sandbox.entry.UnixSocketChannel", return_value=mock_channel), \
             patch("everstaff.sandbox.entry._run_agent", new_callable=AsyncMock) as mock_run:
            await sandbox_main(
                socket_path=str(tmp_path / "test.sock"),
                token="test-token",
                session_id="s1",
                agent_spec_json='{"name":"test"}',
                workspace_dir=str(tmp_path),
            )

        mock_channel.connect.assert_awaited_once_with(str(tmp_path / "test.sock"))
        mock_channel.send_request.assert_awaited_once_with("auth", {"token": "test-token"})
        mock_run.assert_awaited_once()

    async def test_registers_cancel_handler(self, tmp_path):
        """sandbox_main should register a cancel push handler."""
        mock_channel = MagicMock()
        mock_channel.connect = AsyncMock()
        mock_channel.send_request = AsyncMock(return_value={"secrets": {}})
        mock_channel.on_push = MagicMock()
        mock_channel.close = AsyncMock()

        with patch("everstaff.sandbox.entry.UnixSocketChannel", return_value=mock_channel), \
             patch("everstaff.sandbox.entry._run_agent", new_callable=AsyncMock):
            await sandbox_main(
                socket_path="/tmp/test.sock",
                token="t",
                session_id="s1",
                agent_spec_json='{"name":"test"}',
                workspace_dir=str(tmp_path),
            )

        # Verify cancel and hitl.resolution handlers were registered
        push_methods = [call.args[0] for call in mock_channel.on_push.call_args_list]
        assert "cancel" in push_methods
        assert "hitl.resolution" in push_methods

    async def test_closes_channel_on_exit(self, tmp_path):
        """Channel should be closed even if _run_agent raises."""
        mock_channel = MagicMock()
        mock_channel.connect = AsyncMock()
        mock_channel.send_request = AsyncMock(return_value={"secrets": {}})
        mock_channel.on_push = MagicMock()
        mock_channel.close = AsyncMock()

        with patch("everstaff.sandbox.entry.UnixSocketChannel", return_value=mock_channel), \
             patch("everstaff.sandbox.entry._run_agent", new_callable=AsyncMock,
                   side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError, match="boom"):
                await sandbox_main(
                    socket_path="/tmp/test.sock",
                    token="t",
                    session_id="s1",
                    agent_spec_json='{"name":"test"}',
                    workspace_dir=str(tmp_path),
                )

        mock_channel.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_agent_forwards_stream_events():
    """_run_agent sends stream events via IPC notification."""
    channel = AsyncMock()
    channel.send_notification = AsyncMock()

    mock_event_1 = MagicMock()
    mock_event_1.model_dump.return_value = {"type": "text_delta", "content": "hi"}
    mock_event_2 = MagicMock()
    mock_event_2.model_dump.return_value = {"type": "session_end", "response": "done"}

    mock_runtime = AsyncMock()

    async def fake_stream(*args, **kwargs):
        yield mock_event_1
        yield mock_event_2

    mock_runtime.run_stream = fake_stream
    mock_ctx = AsyncMock()

    with patch("everstaff.builder.agent_builder.AgentBuilder") as MockBuilder:
        MockBuilder.return_value.build = AsyncMock(return_value=(mock_runtime, mock_ctx))
        env = MagicMock()
        await _run_agent(
            env=env,
            session_id="s1",
            agent_spec_json='{"agent_name": "test"}',
            cancellation=MagicMock(),
            hitl_resolutions=asyncio.Queue(),
            channel=channel,
            user_input="hello",
        )

    calls = channel.send_notification.call_args_list
    stream_calls = [c for c in calls if c[0][0] == "stream.event"]
    assert len(stream_calls) == 2
    assert stream_calls[0][0][1]["type"] == "text_delta"
    assert stream_calls[0][0][1]["session_id"] == "s1"
    assert stream_calls[1][0][1]["type"] == "session_end"


@pytest.mark.asyncio
async def test_run_agent_passes_cancellation_to_builder():
    """_run_agent should pass the cancellation event to AgentBuilder as parent_cancellation."""
    from everstaff.protocols import CancellationEvent

    cancellation = CancellationEvent()

    mock_runtime = AsyncMock()

    async def fake_stream(*args, **kwargs):
        if False:
            yield  # make it an async generator

    mock_runtime.run_stream = fake_stream
    mock_ctx = AsyncMock()

    with patch("everstaff.builder.agent_builder.AgentBuilder") as MockBuilder:
        MockBuilder.return_value.build = AsyncMock(return_value=(mock_runtime, mock_ctx))
        env = MagicMock()
        await _run_agent(
            env=env,
            session_id="s1",
            agent_spec_json='{"agent_name": "test"}',
            cancellation=cancellation,
            hitl_resolutions=asyncio.Queue(),
            channel=None,
            user_input="hi",
        )

    # Verify AgentBuilder was constructed with parent_cancellation
    call_kwargs = MockBuilder.call_args
    assert call_kwargs.kwargs.get("parent_cancellation") is cancellation


@pytest.mark.asyncio
async def test_cancel_handler_triggers_cancellation_event(tmp_path):
    """Cancel push handler should call cancel() on the shared CancellationEvent."""
    mock_channel = MagicMock()
    mock_channel.connect = AsyncMock()
    mock_channel.send_request = AsyncMock(return_value={"secrets": {}})
    mock_channel.close = AsyncMock()

    # Capture the cancel handler registered via on_push
    cancel_handler = None

    def capture_on_push(method, handler):
        nonlocal cancel_handler
        if method == "cancel":
            cancel_handler = handler

    mock_channel.on_push = MagicMock(side_effect=capture_on_push)

    with patch("everstaff.sandbox.entry.UnixSocketChannel", return_value=mock_channel), \
         patch("everstaff.sandbox.entry._run_agent", new_callable=AsyncMock) as mock_run:
        await sandbox_main(
            socket_path="/tmp/test.sock",
            token="t",
            session_id="s1",
            agent_spec_json='{"name":"test"}',
            workspace_dir=str(tmp_path),
        )

    assert cancel_handler is not None, "cancel handler should have been registered"

    # Verify the cancellation event was passed to _run_agent
    call_kwargs = mock_run.call_args
    cancellation_event = call_kwargs.kwargs.get("cancellation")
    assert cancellation_event is not None
    assert not cancellation_event.is_cancelled

    # Trigger the cancel handler
    await cancel_handler({"force": False})
    assert cancellation_event.is_cancelled


def test_parse_args_user_input():
    """--user-input is parsed correctly."""
    args = parse_args([
        "--socket-path", "/tmp/s", "--token", "t", "--session-id", "s1",
        "--agent-spec", "{}", "--user-input", "hello world",
    ])
    assert args.user_input == "hello world"


def test_parse_args_user_input_default():
    """--user-input defaults to None."""
    args = parse_args([
        "--socket-path", "/tmp/s", "--token", "t", "--session-id", "s1",
        "--agent-spec", "{}",
    ])
    assert args.user_input is None

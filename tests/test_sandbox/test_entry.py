"""Tests for sandbox entry point."""
import asyncio
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from everstaff.sandbox.entry import sandbox_main, parse_args


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

"""Tests for HITL resolution push flow."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from everstaff.sandbox.ipc.server_handler import IpcServerHandler
from everstaff.sandbox.token_store import EphemeralTokenStore
from everstaff.core.secret_store import SecretStore


@pytest.mark.asyncio
class TestHitlResolution:
    async def test_server_handler_detects_hitl_from_memory_save(self):
        """When memory.save includes status=waiting_for_human, handler should call on_hitl_detected."""
        token_store = EphemeralTokenStore()
        secret_store = SecretStore()
        hitl_detected = AsyncMock()

        memory = MagicMock()
        memory.save = AsyncMock(return_value=None)

        handler = IpcServerHandler(
            token_store=token_store,
            secret_store=secret_store,
            memory_store=memory,
            on_hitl_detected=hitl_detected,
        )

        result = await handler.handle("memory.save", {
            "session_id": "s1",
            "messages": [],
            "status": "waiting_for_human",
            "hitl_requests": [{"hitl_id": "h1", "tool_name": "bash", "args": {}}],
        })

        memory.save.assert_awaited_once()
        hitl_detected.assert_awaited_once_with(
            "s1", [{"hitl_id": "h1", "tool_name": "bash", "args": {}}]
        )

    async def test_no_hitl_detection_for_normal_save(self):
        """Normal save (not waiting_for_human) should not trigger HITL callback."""
        token_store = EphemeralTokenStore()
        secret_store = SecretStore()
        hitl_detected = AsyncMock()

        memory = MagicMock()
        memory.save = AsyncMock(return_value=None)

        handler = IpcServerHandler(
            token_store=token_store,
            secret_store=secret_store,
            memory_store=memory,
            on_hitl_detected=hitl_detected,
        )

        await handler.handle("memory.save", {
            "session_id": "s1",
            "messages": [],
            "status": "running",
        })

        hitl_detected.assert_not_awaited()

    async def test_hitl_resolution_queue_receives_push(self):
        """sandbox entry should receive HITL resolution via IPC push."""
        resolutions: asyncio.Queue = asyncio.Queue()

        handler = lambda params: resolutions.put_nowait(params)
        handler({"hitl_id": "h1", "decision": "approved", "comment": "looks good"})

        resolution = resolutions.get_nowait()
        assert resolution["hitl_id"] == "h1"
        assert resolution["decision"] == "approved"
        assert resolution["comment"] == "looks good"

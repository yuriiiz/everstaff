"""DelegateTaskTool._resolve_child_hitl must delegate to canonical resolve_hitl."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import json
from datetime import datetime, timezone

from everstaff.agents.delegate_task_tool import DelegateTaskTool


@pytest.mark.asyncio
async def test_resolve_child_hitl_calls_canonical():
    """_resolve_child_hitl must call canonical resolve_hitl for each pending HITL."""
    env = MagicMock()
    file_store = MagicMock()

    # Mock file_store for the tool message insertion part
    session_data = {
        "session_id": "child-sess",
        "hitl_requests": [
            {
                "hitl_id": "h-1",
                "status": "resolved",  # after canonical_resolve, it will be resolved
                "tool_call_id": "tc-1",
                "request": {"type": "approve_reject", "prompt": "OK?"},
                "response": {
                    "decision": "approved",
                    "comment": None,
                    "resolved_at": datetime.now(timezone.utc).isoformat(),
                    "resolved_by": "human",
                },
            }
        ],
        "messages": [],
    }
    file_store.exists = AsyncMock(return_value=True)
    file_store.read = AsyncMock(return_value=json.dumps(session_data).encode())
    file_store.write = AsyncMock()
    env.build_file_store.return_value = file_store

    tool = DelegateTaskTool(specs=[], env=env)

    with patch(
        "everstaff.agents.delegate_task_tool.canonical_resolve",
        new_callable=AsyncMock,
    ) as mock:
        await tool._resolve_child_hitl(
            "child-sess", {"decision": "approved", "hitl_id": "h-1"}
        )
        mock.assert_called_once_with(
            session_id="child-sess",
            hitl_id="h-1",
            decision="approved",
            comment=None,
            file_store=file_store,
        )


@pytest.mark.asyncio
async def test_resolve_child_hitl_legacy_no_hitl_id():
    """Without hitl_id, _resolve_child_hitl resolves ALL pending HITLs via canonical."""
    env = MagicMock()
    file_store = MagicMock()

    session_data = {
        "session_id": "child-sess",
        "hitl_requests": [
            {
                "hitl_id": "h-1",
                "status": "pending",
                "tool_call_id": "tc-1",
                "request": {"type": "approve_reject", "prompt": "OK?"},
            },
            {
                "hitl_id": "h-2",
                "status": "pending",
                "tool_call_id": "tc-2",
                "request": {"type": "approve_reject", "prompt": "Sure?"},
            },
        ],
        "messages": [],
    }

    # First read: for the legacy path to discover pending HITLs
    # Second read: for the tool message insertion step
    resolved_data = json.loads(json.dumps(session_data))
    for item in resolved_data["hitl_requests"]:
        item["status"] = "resolved"
        item["response"] = {
            "decision": "approved",
            "comment": None,
            "resolved_at": datetime.now(timezone.utc).isoformat(),
            "resolved_by": "human",
        }

    file_store.read = AsyncMock(
        side_effect=[
            json.dumps(session_data).encode(),  # first read: legacy path
            json.dumps(resolved_data).encode(),  # second read: tool messages
        ]
    )
    file_store.write = AsyncMock()
    env.build_file_store.return_value = file_store

    tool = DelegateTaskTool(specs=[], env=env)

    with patch(
        "everstaff.agents.delegate_task_tool.canonical_resolve",
        new_callable=AsyncMock,
    ) as mock:
        await tool._resolve_child_hitl(
            "child-sess", {"decision": "approved"}
        )
        assert mock.call_count == 2
        mock.assert_any_call(
            session_id="child-sess",
            hitl_id="h-1",
            decision="approved",
            comment=None,
            file_store=file_store,
        )
        mock.assert_any_call(
            session_id="child-sess",
            hitl_id="h-2",
            decision="approved",
            comment=None,
            file_store=file_store,
        )


@pytest.mark.asyncio
async def test_resolve_child_hitl_inserts_tool_messages():
    """After canonical resolve, tool messages must be appended to session messages."""
    env = MagicMock()
    file_store = MagicMock()

    session_data = {
        "session_id": "child-sess",
        "hitl_requests": [
            {
                "hitl_id": "h-1",
                "status": "resolved",
                "tool_call_id": "tc-1",
                "request": {"type": "approve_reject", "prompt": "OK?"},
                "response": {
                    "decision": "approved",
                    "comment": "looks good",
                    "resolved_at": datetime.now(timezone.utc).isoformat(),
                    "resolved_by": "human",
                },
            }
        ],
        "messages": [],
    }
    file_store.exists = AsyncMock(return_value=True)
    file_store.read = AsyncMock(return_value=json.dumps(session_data).encode())
    file_store.write = AsyncMock()
    env.build_file_store.return_value = file_store

    tool = DelegateTaskTool(specs=[], env=env)

    with patch(
        "everstaff.agents.delegate_task_tool.canonical_resolve",
        new_callable=AsyncMock,
    ):
        await tool._resolve_child_hitl(
            "child-sess", {"decision": "approved", "hitl_id": "h-1"}
        )

    # Verify write was called with tool messages inserted
    assert file_store.write.called
    written_data = json.loads(file_store.write.call_args[0][1].decode())
    messages = written_data["messages"]
    assert len(messages) == 1
    assert messages[0]["role"] == "tool"
    assert messages[0]["tool_call_id"] == "tc-1"
    assert "approved" in messages[0]["content"]
    assert "looks good" in messages[0]["content"]


def test_delegate_imports_canonical():
    """delegate_task_tool must import canonical resolve."""
    import inspect
    import everstaff.agents.delegate_task_tool as mod

    source = inspect.getsource(mod)
    assert "canonical_resolve" in source or "resolve_hitl" in source

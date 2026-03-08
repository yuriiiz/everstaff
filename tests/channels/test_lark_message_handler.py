import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from everstaff.channels.lark_message_handler import LarkMessageHandler


@pytest.fixture
def handler():
    adapter = MagicMock()
    adapter.send_text = AsyncMock(return_value="msg-1")
    adapter.send_card = AsyncMock(return_value="msg-2")
    adapter.delete_message = AsyncMock()
    bus = MagicMock()
    create_fn = AsyncMock(return_value="sess-123")
    return LarkMessageHandler(
        adapter=adapter,
        event_bus=bus,
        agents_dir="/tmp/nonexistent",
        session_create_fn=create_fn,
    )


@pytest.mark.asyncio
async def test_on_agent_selected_retracts_and_creates(handler):
    handler._pending_selections["mid-1"] = {
        "sender_open_id": "u1",
        "chat_id": "oc_1",
        "user_input": "hello",
    }
    result = await handler.on_agent_selected(
        "mid-1",
        {"agent_name": "my-agent", "sender_open_id": "u1", "user_input": "hello"},
        "u1",
    )
    handler._adapter.delete_message.assert_awaited_once_with("mid-1")
    handler._session_create_fn.assert_awaited_once()
    assert result["toast"]["type"] == "success"


@pytest.mark.asyncio
async def test_on_agent_selected_rejects_wrong_sender(handler):
    handler._pending_selections["mid-1"] = {
        "sender_open_id": "u1",
        "chat_id": "oc_1",
        "user_input": "hello",
    }
    result = await handler.on_agent_selected(
        "mid-1",
        {"agent_name": "my-agent", "sender_open_id": "u1"},
        "u2",  # wrong sender
    )
    assert result["toast"]["type"] == "warning"


@pytest.mark.asyncio
async def test_deliver_result_short_text(handler):
    await handler.deliver_result("s1", "oc_1", "short result")
    handler._adapter.send_text.assert_awaited_once_with("oc_1", "short result")


@pytest.mark.asyncio
async def test_deliver_result_long_text(handler):
    long_text = "x" * 600
    await handler.deliver_result("s1", "oc_1", long_text)
    handler._adapter.send_card.assert_awaited_once()


@pytest.mark.asyncio
async def test_build_agent_selection_card(handler):
    agents = [
        {"name": "agent-a", "uuid": "u1", "description": "desc a"},
        {"name": "agent-b", "uuid": "u2", "description": "desc b"},
    ]
    card = handler._build_agent_selection_card(agents, "sender1", "hello")
    assert card["header"]["title"]["content"] == "Select Agent"
    actions = card["elements"][1]["actions"]
    assert len(actions) == 2
    assert actions[0]["type"] == "primary"
    assert actions[1]["type"] == "default"

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from everstaff.channels.lark_message_handler import LarkMessageHandler


@pytest.fixture
def handler():
    adapter = MagicMock()
    adapter.send_text = AsyncMock(return_value="msg-1")
    adapter.send_card = AsyncMock(return_value="msg-2")
    adapter.delete_message = AsyncMock()
    adapter.resolve_username = AsyncMock(return_value="TestUser")
    adapter.create_chat_group = AsyncMock(return_value="oc_new_group")
    adapter.add_chat_members = AsyncMock()
    bus = MagicMock()
    create_fn = AsyncMock(return_value="sess-123")
    return LarkMessageHandler(
        adapter=adapter,
        event_bus=bus,
        agents_dir="/tmp/nonexistent",
        session_create_fn=create_fn,
        bot_name="TestBot",
    )


@pytest.mark.asyncio
async def test_on_agent_selected_creates_group_and_session(handler):
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
    handler._adapter.resolve_username.assert_awaited_once_with("u1")
    handler._adapter.create_chat_group.assert_awaited_once_with(
        "TestBot - TestUser - my-agent", "u1"
    )
    handler._adapter.add_chat_members.assert_awaited_once_with("oc_new_group", ["u1"])
    handler._session_create_fn.assert_awaited_once()
    # Session should be created with new group chat_id
    call_args = handler._session_create_fn.call_args
    source_info = call_args[0][2]
    assert source_info["chat_id"] == "oc_new_group"
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
async def test_deliver_result_as_card(handler):
    await handler.deliver_result("s1", "oc_1", "short result")
    handler._adapter.send_card.assert_awaited_once()
    card = handler._adapter.send_card.call_args[0][1]
    assert card["elements"][0]["tag"] == "markdown"
    assert card["elements"][0]["content"] == "short result"


@pytest.mark.asyncio
async def test_deliver_result_long_text(handler):
    long_text = "x" * 2100
    await handler.deliver_result("s1", "oc_1", long_text)
    handler._adapter.send_card.assert_awaited_once()
    card = handler._adapter.send_card.call_args[0][1]
    assert len(card["elements"]) == 2  # content + truncation note


@pytest.mark.asyncio
async def test_build_agent_selection_card(handler):
    agents = [
        {"name": "agent-a", "uuid": "u1", "description": "desc a"},
        {"name": "agent-b", "uuid": "u2", "description": "desc b"},
    ]
    card = handler._build_agent_selection_card(agents, "sender1", "hello")
    assert card["header"]["title"]["content"] == "Select Agent"
    # Each agent should have a markdown + action pair
    # Structure: [message_markdown, agent_a_markdown, agent_a_action, agent_b_markdown, agent_b_action]
    action_elements = [e for e in card["elements"] if e["tag"] == "action"]
    assert len(action_elements) == 2
    # Each action should have a "Start Session" button
    for action_el in action_elements:
        btn = action_el["actions"][0]
        assert btn["text"]["content"] == "Start Session"
        assert btn["type"] == "primary"


@pytest.mark.asyncio
async def test_handle_help_command(handler):
    event = MagicMock()
    event.type = "lark_message"
    event.payload = {
        "chat_id": "oc_1",
        "sender_open_id": "u1",
        "content": "/help",
    }
    await handler._handle_message(event)
    handler._adapter.send_card.assert_awaited_once()
    card = handler._adapter.send_card.call_args[0][1]
    assert card["header"]["title"]["content"] == "Help"
    assert "/help" in card["elements"][0]["content"]

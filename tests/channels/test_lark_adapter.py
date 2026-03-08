import pytest
from unittest.mock import AsyncMock, MagicMock
from everstaff.channels.lark_adapter import LarkChannelAdapter


@pytest.mark.asyncio
async def test_send_text_delegates():
    conn = MagicMock()
    conn.send_text = AsyncMock(return_value="msg-1")
    adapter = LarkChannelAdapter(conn)
    result = await adapter.send_text("oc_123", "hello")
    assert result == "msg-1"
    conn.send_text.assert_awaited_once_with("oc_123", "hello")


@pytest.mark.asyncio
async def test_send_card_delegates():
    conn = MagicMock()
    conn.send_card = AsyncMock(return_value="msg-2")
    adapter = LarkChannelAdapter(conn)
    result = await adapter.send_card("oc_123", {"header": {}})
    assert result == "msg-2"


@pytest.mark.asyncio
async def test_update_card_delegates():
    conn = MagicMock()
    conn.update_card = AsyncMock()
    adapter = LarkChannelAdapter(conn)
    await adapter.update_card("mid-1", {"elements": []})
    conn.update_card.assert_awaited_once_with("mid-1", {"elements": []})

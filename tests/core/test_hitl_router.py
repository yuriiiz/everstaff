import pytest
from unittest.mock import AsyncMock, MagicMock
from everstaff.core.hitl_router import HitlRouter


@pytest.fixture
def router():
    return HitlRouter()


@pytest.mark.asyncio
async def test_route_to_source_handler(router):
    handler = AsyncMock()
    router.register_handler("lark", handler)
    router.set_session_source("sess-1", "lark", {"chat_id": "oc_123"})

    from everstaff.protocols import HitlRequest
    req = HitlRequest(hitl_id="h1", type="approve_reject", prompt="ok?")
    await router.route("sess-1", req)
    handler.assert_awaited_once_with("sess-1", req, {"chat_id": "oc_123"})


@pytest.mark.asyncio
async def test_fallback_to_channel_manager(router):
    cm = AsyncMock()
    router.channel_manager = cm

    from everstaff.protocols import HitlRequest
    req = HitlRequest(hitl_id="h2", type="approve_reject", prompt="ok?")
    await router.route("sess-unknown", req)
    cm.broadcast.assert_awaited_once_with("sess-unknown", req)


@pytest.mark.asyncio
async def test_fallback_on_handler_error(router):
    handler = AsyncMock(side_effect=Exception("boom"))
    router.register_handler("lark", handler)
    router.set_session_source("sess-1", "lark", {})

    cm = AsyncMock()
    router.channel_manager = cm

    from everstaff.protocols import HitlRequest
    req = HitlRequest(hitl_id="h3", type="approve_reject", prompt="ok?")
    await router.route("sess-1", req)
    cm.broadcast.assert_awaited_once_with("sess-1", req)


@pytest.mark.asyncio
async def test_no_handler_no_cm_logs_warning(router):
    from everstaff.protocols import HitlRequest
    req = HitlRequest(hitl_id="h4", type="approve_reject", prompt="ok?")
    # Should not raise
    await router.route("sess-1", req)

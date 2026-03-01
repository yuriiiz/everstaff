import pytest


@pytest.mark.asyncio
async def test_send_request_posts_json(monkeypatch):
    """send_request POSTs a JSON payload to the configured URL."""
    from everstaff.channels.http_webhook import HttpWebhookChannel
    from everstaff.protocols import HitlRequest

    calls = []

    class _FakeResp:
        status = 200
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass

    class _FakeSession:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        def post(self, url, *, json, headers):
            calls.append({"url": url, "json": json, "headers": headers})
            return _FakeResp()

    class _FakeAiohttp:
        ClientSession = _FakeSession

    import everstaff.channels.http_webhook as mod
    monkeypatch.setattr(mod, "aiohttp", _FakeAiohttp())

    ch = HttpWebhookChannel(url="https://example.com/hook", headers={"X-Token": "abc"})
    req = HitlRequest(
        hitl_id="h1",
        type="approve_reject",
        prompt="Approve?",
        context="ctx",
        options=[],
        timeout_seconds=3600,
    )
    await ch.send_request("sess-1", req)

    assert len(calls) == 1
    assert calls[0]["url"] == "https://example.com/hook"
    assert calls[0]["json"]["hitl_id"] == "h1"
    assert calls[0]["json"]["session_id"] == "sess-1"
    assert calls[0]["headers"]["X-Token"] == "abc"


@pytest.mark.asyncio
async def test_on_resolved_is_noop():
    from everstaff.channels.http_webhook import HttpWebhookChannel
    from everstaff.protocols import HitlResolution
    from datetime import datetime, timezone

    ch = HttpWebhookChannel(url="https://example.com/hook")
    res = HitlResolution(
        decision="approved",
        resolved_by="user",
        resolved_at=datetime.now(timezone.utc),
    )
    await ch.on_resolved("h1", res)  # must not raise


def test_build_channel_webhook(tmp_path):
    from everstaff.core.config import WebhookChannelConfig
    from everstaff.core.factories import build_channel
    from everstaff.channels.http_webhook import HttpWebhookChannel
    from everstaff.storage.local import LocalFileStore

    store = LocalFileStore(str(tmp_path))
    cfg = WebhookChannelConfig(type="webhook", url="https://hooks.example.com/x")
    ch = build_channel(cfg, store)
    assert isinstance(ch, HttpWebhookChannel)

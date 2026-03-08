"""Tests for Feishu UAT token storage."""
import pytest
import time
from pathlib import Path

from everstaff.feishu.token_store import (
    StoredToken,
    token_status,
    FileTokenStore,
)


def test_token_status_valid():
    t = StoredToken(
        app_id="app", user_open_id="user",
        access_token="at", refresh_token="rt",
        expires_at=int(time.time() * 1000) + 600_000,  # 10 min from now
        refresh_expires_at=int(time.time() * 1000) + 86400_000,
        scope="cal:cal", granted_at=int(time.time() * 1000),
    )
    assert token_status(t) == "valid"


def test_token_status_needs_refresh():
    now = int(time.time() * 1000)
    t = StoredToken(
        app_id="app", user_open_id="user",
        access_token="at", refresh_token="rt",
        expires_at=now + 60_000,  # 1 min from now (< 5 min threshold)
        refresh_expires_at=now + 86400_000,
        scope="", granted_at=now,
    )
    assert token_status(t) == "needs_refresh"


def test_token_status_expired():
    t = StoredToken(
        app_id="app", user_open_id="user",
        access_token="at", refresh_token="rt",
        expires_at=1000, refresh_expires_at=1000,
        scope="", granted_at=1000,
    )
    assert token_status(t) == "expired"


@pytest.mark.asyncio
async def test_file_store_roundtrip(tmp_path: Path):
    store = FileTokenStore(base_dir=tmp_path)
    t = StoredToken(
        app_id="app123", user_open_id="ou_user1",
        access_token="at_xxx", refresh_token="rt_xxx",
        expires_at=int(time.time() * 1000) + 600_000,
        refresh_expires_at=int(time.time() * 1000) + 86400_000,
        scope="calendar:calendar", granted_at=int(time.time() * 1000),
    )
    await store.set(t)
    loaded = await store.get("app123", "ou_user1")
    assert loaded is not None
    assert loaded.access_token == "at_xxx"
    assert loaded.scope == "calendar:calendar"


@pytest.mark.asyncio
async def test_file_store_get_missing(tmp_path: Path):
    store = FileTokenStore(base_dir=tmp_path)
    assert await store.get("nope", "nope") is None


@pytest.mark.asyncio
async def test_file_store_remove(tmp_path: Path):
    store = FileTokenStore(base_dir=tmp_path)
    t = StoredToken(
        app_id="app", user_open_id="user",
        access_token="at", refresh_token="rt",
        expires_at=0, refresh_expires_at=0, scope="", granted_at=0,
    )
    await store.set(t)
    await store.remove("app", "user")
    assert await store.get("app", "user") is None

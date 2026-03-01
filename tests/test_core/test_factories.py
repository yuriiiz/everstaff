"""Tests for src/core/factories.py"""
import pytest


# ── Storage ──────────────────────────────────────────────────────────────────

def test_build_file_store_local(tmp_path):
    from everstaff.core.config import StorageConfig
    from everstaff.core.factories import build_file_store
    from everstaff.storage.local import LocalFileStore

    cfg = StorageConfig(type="local")
    store = build_file_store(cfg, str(tmp_path))
    assert isinstance(store, LocalFileStore)


def test_build_file_store_unknown_type_raises():
    from everstaff.core.config import StorageConfig
    from everstaff.core.factories import build_file_store

    cfg = StorageConfig(type="unknown_backend")
    with pytest.raises(ValueError, match="Unknown storage type"):
        build_file_store(cfg, "/tmp")


# ── Tracers ───────────────────────────────────────────────────────────────────

def test_build_tracer_empty_list_returns_null_tracer(tmp_path):
    from everstaff.core.factories import build_tracer
    from everstaff.nulls import NullTracer
    from everstaff.storage.local import LocalFileStore

    store = LocalFileStore(str(tmp_path))
    result = build_tracer([], "sess-1", store)
    assert isinstance(result, NullTracer)


def test_build_tracer_single_file_returns_file_tracer(tmp_path):
    from everstaff.core.config import TracerConfig
    from everstaff.core.factories import build_tracer
    from everstaff.tracing.file_tracer import FileTracer
    from everstaff.storage.local import LocalFileStore

    store = LocalFileStore(str(tmp_path))
    result = build_tracer([TracerConfig(type="file")], "sess-1", store)
    assert isinstance(result, FileTracer)


def test_build_tracer_multiple_returns_composite(tmp_path):
    from everstaff.core.config import TracerConfig
    from everstaff.core.factories import build_tracer
    from everstaff.tracing.composite import CompositeTracer
    from everstaff.storage.local import LocalFileStore

    store = LocalFileStore(str(tmp_path))
    result = build_tracer(
        [TracerConfig(type="file"), TracerConfig(type="console")],
        "sess-1",
        store,
    )
    assert isinstance(result, CompositeTracer)


def test_build_tracer_unknown_type_raises(tmp_path):
    from everstaff.core.config import TracerConfig
    from everstaff.core.factories import build_tracer
    from everstaff.storage.local import LocalFileStore

    store = LocalFileStore(str(tmp_path))
    with pytest.raises(ValueError, match="Unknown tracer type"):
        build_tracer([TracerConfig(type="mystery")], "sess-1", store)


# ── Channels ──────────────────────────────────────────────────────────────────

def test_build_channel_lark(tmp_path):
    from everstaff.core.config import LarkChannelConfig
    from everstaff.core.factories import build_channel
    from everstaff.channels.lark import LarkChannel
    from everstaff.storage.local import LocalFileStore

    store = LocalFileStore(str(tmp_path))
    cfg = LarkChannelConfig(
        type="lark",
        app_id="cli_test",
        app_secret="secret",
        verification_token="tok",
        chat_id="oc_abc",
        bot_name="TestBot",
    )
    ch = build_channel(cfg, store)
    assert isinstance(ch, LarkChannel)


def test_build_channel_manager_empty_channels(tmp_path):
    from everstaff.channels.manager import ChannelManager
    from everstaff.core.factories import build_channel_manager
    from everstaff.storage.local import LocalFileStore

    class _FakeCfg:
        channels = {}

    store = LocalFileStore(str(tmp_path))
    cm = build_channel_manager(_FakeCfg(), store)
    assert isinstance(cm, ChannelManager)
    assert len(cm._channels) == 0

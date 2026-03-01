"""Factory functions for building runtime components from config."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from everstaff.core.config import StorageConfig, TracerConfig, ChannelConfig
    from everstaff.protocols import FileStore, TracingBackend, HitlChannel


def build_memory_store(cfg: "StorageConfig", sessions_dir: str, memory_dir: str):
    """Construct a FileMemoryStore with dual FileStore (session + memory)."""
    from everstaff.memory.file_store import FileMemoryStore
    session_store = build_file_store(cfg, sessions_dir)
    try:
        memory_store = build_file_store(cfg, memory_dir)
    except Exception:
        memory_store = None
    return FileMemoryStore(session_store, memory_store=memory_store)


def build_file_store(cfg: "StorageConfig", sessions_dir: str) -> "FileStore":
    """Construct a FileStore from StorageConfig."""
    if cfg.type == "local":
        from everstaff.storage.local import LocalFileStore
        return LocalFileStore(sessions_dir)
    elif cfg.type == "s3":
        from everstaff.storage.s3 import S3FileStore
        return S3FileStore(
            bucket=cfg.s3_bucket,
            prefix=cfg.s3_prefix,
            region=cfg.s3_region,
            endpoint_url=cfg.s3_endpoint_url,
            access_key=cfg.s3_access_key,
            secret_key=cfg.s3_secret_key,
        )
    raise ValueError(f"Unknown storage type: {cfg.type!r}")


def build_tracer(
    cfgs: "list[TracerConfig]",
    session_id: str,
    file_store: "FileStore",
) -> "TracingBackend":
    """Construct a TracingBackend (possibly composite) from a list of TracerConfig."""
    if not cfgs:
        from everstaff.nulls import NullTracer
        return NullTracer()

    backends: list = []
    for cfg in cfgs:
        if cfg.type == "file":
            from everstaff.tracing.file_tracer import FileTracer
            session_path = f"{session_id}/traces.jsonl" if session_id else None
            global_path = "traces.jsonl"
            backends.append(FileTracer(
                session_path=session_path,
                global_path=global_path,
                store=file_store,
            ))
        elif cfg.type == "console":
            from everstaff.tracing.console import ConsoleTracer
            backends.append(ConsoleTracer())
        elif cfg.type == "otlp":
            # OTLP tracer not yet implemented — src/tracing/otlp.py does not exist
            raise NotImplementedError("OTLP tracer not yet implemented")
        else:
            raise ValueError(f"Unknown tracer type: {cfg.type!r}")

    if len(backends) == 1:
        return backends[0]
    from everstaff.tracing.composite import CompositeTracer
    return CompositeTracer(backends)


def build_channel_manager(config, file_store: "FileStore"):
    """Construct a ChannelManager with all configured channels.

    Handles post-injection of channel_manager + config into LarkWsChannel
    instances (circular dependency: channel needs its own manager).
    """
    from everstaff.channels.manager import ChannelManager
    cm = ChannelManager()
    for name, ch_cfg in (config.channels or {}).items():
        ch = build_channel(ch_cfg, file_store)
        cm.register(ch)
    # Post-inject into LarkWsChannel instances
    from everstaff.channels.lark_ws import LarkWsChannel
    for ch in cm._channels:
        if isinstance(ch, LarkWsChannel):
            ch._channel_manager = cm
            ch._config = config
    return cm


def build_channel(cfg: "ChannelConfig", file_store: "FileStore") -> "HitlChannel":
    """Construct a HitlChannel from a typed ChannelConfig."""
    from everstaff.core.config import LarkChannelConfig, LarkWsChannelConfig, WebhookChannelConfig
    if isinstance(cfg, LarkChannelConfig):
        from everstaff.channels.lark import LarkChannel
        return LarkChannel(
            app_id=cfg.app_id,
            app_secret=cfg.app_secret,
            verification_token=cfg.verification_token,
            chat_id=cfg.chat_id,
            bot_name=cfg.bot_name,
            file_store=file_store,
            domain=cfg.domain,
        )
    elif isinstance(cfg, LarkWsChannelConfig):
        try:
            import lark_oapi  # noqa: F401
        except ImportError:
            raise ImportError(
                "lark-oapi is required for LarkWsChannel. "
                "Install it with: pip install 'everstaff[lark]'"
            ) from None
        from everstaff.channels.lark_ws import LarkWsChannel
        return LarkWsChannel(
            app_id=cfg.app_id,
            app_secret=cfg.app_secret,
            chat_id=cfg.chat_id,
            bot_name=cfg.bot_name,
            file_store=file_store,
            domain=cfg.domain,
        )
    elif isinstance(cfg, WebhookChannelConfig):
        from everstaff.channels.http_webhook import HttpWebhookChannel
        return HttpWebhookChannel(url=cfg.url, headers=cfg.headers)
    raise ValueError(f"Unknown channel type: {cfg.type!r}")


def build_channel_registry(config, file_store: "FileStore") -> dict:
    """Return {name: HitlChannel} for all configured named channels."""
    registry = {}
    for name, ch_cfg in (config.channels or {}).items():
        registry[name] = build_channel(ch_cfg, file_store)
    return registry


def build_channel_manager_from_registry(registry: dict, config) -> "ChannelManager":
    """Build a ChannelManager from a pre-built channel registry, sharing instances.

    Unlike build_channel_manager(), this function reuses the channel instances
    already created in the registry so that both the ChannelManager and the
    channel_registry dict point to the same objects.  This ensures channels are
    started/stopped exactly once and that LarkWsChannel post-injection reaches
    the same instances that are looked up by name at runtime.
    """
    from everstaff.channels.manager import ChannelManager
    cm = ChannelManager()
    for ch in registry.values():
        cm.register(ch)
    # Post-inject into LarkWsChannel instances
    from everstaff.channels.lark_ws import LarkWsChannel
    for ch in cm._channels:
        if isinstance(ch, LarkWsChannel):
            ch._channel_manager = cm
            ch._config = config
    return cm

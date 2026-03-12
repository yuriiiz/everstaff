from __future__ import annotations

from pathlib import Path
from typing import Any, TYPE_CHECKING
from uuid import uuid4

from everstaff.nulls import InMemoryStore, NullTracer
from everstaff.protocols import LLMClient, MemoryStore, TracingBackend

if TYPE_CHECKING:
    from everstaff.core.config import FrameworkConfig
    from everstaff.protocols import FileStore


class RuntimeEnvironment:
    """Base environment. Override methods to customize for CLI/Web/Test."""

    def __init__(self, config: "FrameworkConfig | None" = None, channel_manager: Any = None, hitl_router: Any = None) -> None:
        from everstaff.core.config import FrameworkConfig as _FC
        self._config: _FC = config if config is not None else _FC()
        self._channel_manager = channel_manager
        self._hitl_router = hitl_router

    @property
    def config(self) -> "FrameworkConfig":
        return self._config

    @property
    def channel_manager(self) -> Any:
        return self._channel_manager

    @property
    def hitl_router(self) -> Any:
        return self._hitl_router

    def build_memory_store(self, max_tokens: int | None = None, **mem0_scope) -> MemoryStore:
        raise NotImplementedError

    def build_file_store(self) -> "FileStore":
        raise NotImplementedError

    def build_tracer(self, session_id: str = "") -> TracingBackend:
        raise NotImplementedError

    def build_llm_client(self, model: str, **kwargs: Any) -> LLMClient:
        from everstaff.llm.litellm_client import LiteLLMClient
        return LiteLLMClient(model=model, **kwargs)

    def build_mem0_provider(self, **mem0_scope):
        """Build Mem0Provider for long-term memory injection. Override in subclass."""
        return None

    def build_mem0_hook(self, provider, memory_store, **mem0_scope):
        """Build Mem0Hook for memory lifecycle events. Override in subclass."""
        return None

    def new_session_id(self) -> str:
        return str(uuid4())

    def working_dir(self, session_id: str, root_session_id: str | None = None) -> Path:
        """Return per-session working directory for file tool operations."""
        return Path.cwd()

    def project_root(self) -> Path:
        """Return the project root directory for loading project context."""
        return Path.cwd()

    def sessions_dir(self) -> str | None:
        """Return the base sessions directory, or None if not applicable."""
        return None

    @property
    def mcp_pool(self):
        """Return shared MCP connection pool, or None."""
        return None


class DefaultEnvironment(RuntimeEnvironment):
    def __init__(
        self,
        sessions_dir: str,
        session_id: str | None = None,  # DEPRECATED: ignored, use AgentBuilder(session_id=) instead
        config=None,              # FrameworkConfig | None
        channel_manager: Any = None,
        hitl_router: Any = None,
        mcp_pool: Any = None,
        session_index: Any = None,  # shared SessionIndex instance
    ) -> None:
        super().__init__(config=config, channel_manager=channel_manager, hitl_router=hitl_router)
        self._sessions_dir = sessions_dir
        self._mcp_pool = mcp_pool
        self._session_index = session_index
        # NOTE: session_id is intentionally NOT stored — use AgentBuilder(session_id=) instead

    def build_file_store(self) -> "FileStore":
        from everstaff.core.factories import build_file_store as _build_file_store
        return _build_file_store(self.config.storage, self._sessions_dir)

    def build_memory_store(self, max_tokens: int | None = None, **mem0_scope) -> MemoryStore:
        from everstaff.memory.file_store import FileMemoryStore
        from everstaff.memory.compressible_store import CompressibleMemoryStore
        from everstaff.session.index import SessionIndex
        index = self._session_index or SessionIndex(Path(self._sessions_dir))
        store = FileMemoryStore(self.build_file_store(), index=index)

        strategy_kwargs = {"max_tokens": max_tokens} if max_tokens is not None else {}
        if self._config.memory.enabled:
            from everstaff.memory.strategies import Mem0ExtractionStrategy
            client = self._get_or_create_mem0_client()
            strategy = Mem0ExtractionStrategy(client, **mem0_scope, **strategy_kwargs)
        else:
            from everstaff.memory.strategies import TruncationStrategy
            strategy = TruncationStrategy(**strategy_kwargs)

        compress_kwargs = {"max_tokens": max_tokens} if max_tokens is not None else {}
        return CompressibleMemoryStore(store, strategy, **compress_kwargs)

    def build_mem0_provider(self, **mem0_scope):
        if not self._config.memory.enabled:
            return None
        from everstaff.memory.mem0_provider import Mem0Provider
        return Mem0Provider(self._get_or_create_mem0_client(), **mem0_scope)

    def build_mem0_hook(self, provider, memory_store, **mem0_scope):
        if not self._config.memory.enabled:
            return None
        from everstaff.memory.mem0_hook import Mem0Hook
        return Mem0Hook(
            mem0_provider=provider,
            mem0_client=self._get_or_create_mem0_client(),
            memory_store=memory_store,
            **mem0_scope,
        )

    def _get_or_create_mem0_client(self):
        if not hasattr(self, "_mem0_client"):
            from everstaff.memory.mem0_client import Mem0Client
            mem = self._config.memory
            llm_model_id = self._config.resolve_model(mem.llm_model_kind).model_id
            embed_model_id = self._config.resolve_model(mem.embedding_model_kind).model_id
            self._mem0_client = Mem0Client(mem, llm_model_id, embed_model_id)
        return self._mem0_client

    def build_tracer(self, session_id: str = "") -> TracingBackend:
        from everstaff.core.factories import build_tracer as _build_tracer
        file_store = self.build_file_store()
        return _build_tracer(self.config.tracers, session_id, file_store)

    def new_session_id(self) -> str:
        return str(uuid4())

    def working_dir(self, session_id: str, root_session_id: str | None = None) -> Path:
        effective_root = root_session_id or session_id
        d = Path(self._sessions_dir) / effective_root / "workspaces"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def sessions_dir(self) -> str | None:
        return self._sessions_dir

    @property
    def mcp_pool(self):
        return self._mcp_pool


class TestEnvironment(RuntimeEnvironment):
    def __init__(self, config: "FrameworkConfig | None" = None) -> None:
        if config is None:
            from everstaff.core.config import FrameworkConfig as _FC
            from everstaff.schema.model_config import ModelMapping
            config = _FC(model_mappings={
                "smart": ModelMapping(model_id="test-model"),
                "fast": ModelMapping(model_id="test-model-fast"),
            })
        super().__init__(config=config)

    def build_memory_store(self, max_tokens: int | None = None, **mem0_scope) -> MemoryStore:
        return InMemoryStore()

    def build_tracer(self, session_id: str = "") -> TracingBackend:
        return NullTracer()

    def build_llm_client(self, model: str, **kwargs: Any) -> LLMClient:
        from unittest.mock import AsyncMock, MagicMock
        from everstaff.protocols import LLMResponse
        client = MagicMock()
        client.complete = AsyncMock(return_value=LLMResponse(content="test response", tool_calls=[]))
        return client

    def working_dir(self, session_id: str, root_session_id: str | None = None) -> Path:
        import tempfile
        return Path(tempfile.mkdtemp())


# Backward-compatible alias — remove after all callers updated
CLIEnvironment = DefaultEnvironment

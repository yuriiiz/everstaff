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

    def __init__(self, config: "FrameworkConfig | None" = None, channel_manager: Any = None) -> None:
        from everstaff.core.config import FrameworkConfig as _FC
        self._config: _FC = config if config is not None else _FC()
        self._channel_manager = channel_manager

    @property
    def config(self) -> "FrameworkConfig":
        return self._config

    @property
    def channel_manager(self) -> Any:
        return self._channel_manager

    def build_memory_store(self, max_tokens: int | None = None) -> MemoryStore:
        raise NotImplementedError

    def build_file_store(self) -> "FileStore":
        raise NotImplementedError

    def build_tracer(self, session_id: str = "") -> TracingBackend:
        raise NotImplementedError

    def build_llm_client(self, model: str, **kwargs: Any) -> LLMClient:
        from everstaff.llm.litellm_client import LiteLLMClient
        return LiteLLMClient(model=model, **kwargs)

    def new_session_id(self) -> str:
        return str(uuid4())

    def working_dir(self, session_id: str) -> Path:
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
        mcp_pool: Any = None,
    ) -> None:
        super().__init__(config=config, channel_manager=channel_manager)
        self._sessions_dir = sessions_dir
        self._mcp_pool = mcp_pool
        # NOTE: session_id is intentionally NOT stored — use AgentBuilder(session_id=) instead

    def build_file_store(self) -> "FileStore":
        from everstaff.core.factories import build_file_store as _build_file_store
        return _build_file_store(self.config.storage, self._sessions_dir)

    def build_memory_store(self, max_tokens: int | None = None) -> MemoryStore:
        from everstaff.memory.file_store import FileMemoryStore
        from everstaff.memory.compressible_store import CompressibleMemoryStore
        from everstaff.memory.strategies import TruncationStrategy
        store = FileMemoryStore(self.build_file_store())
        kwargs = {"max_tokens": max_tokens} if max_tokens is not None else {}
        return CompressibleMemoryStore(store, TruncationStrategy(), **kwargs)

    def build_tracer(self, session_id: str = "") -> TracingBackend:
        from everstaff.core.factories import build_tracer as _build_tracer
        file_store = self.build_file_store()
        return _build_tracer(self.config.tracers, session_id, file_store)

    def new_session_id(self) -> str:
        return str(uuid4())

    def working_dir(self, session_id: str) -> Path:
        d = Path(self._sessions_dir) / session_id / "workspaces"
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

    def build_memory_store(self, max_tokens: int | None = None) -> MemoryStore:
        return InMemoryStore()

    def build_tracer(self, session_id: str = "") -> TracingBackend:
        return NullTracer()

    def build_llm_client(self, model: str, **kwargs: Any) -> LLMClient:
        from unittest.mock import AsyncMock, MagicMock
        from everstaff.protocols import LLMResponse
        client = MagicMock()
        client.complete = AsyncMock(return_value=LLMResponse(content="test response", tool_calls=[]))
        return client

    def working_dir(self, session_id: str) -> Path:
        import tempfile
        return Path(tempfile.mkdtemp())


# Backward-compatible alias — remove after all callers updated
CLIEnvironment = DefaultEnvironment

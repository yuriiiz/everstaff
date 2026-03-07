"""SandboxEnvironment — RuntimeEnvironment for sandbox processes."""
from __future__ import annotations

from pathlib import Path
from typing import Any, TYPE_CHECKING

from everstaff.builder.environment import RuntimeEnvironment
from everstaff.sandbox.proxy.memory_store import ProxyMemoryStore
from everstaff.sandbox.proxy.tracer import ProxyTracer
from everstaff.sandbox.proxy.file_store import ProxyFileStore

if TYPE_CHECKING:
    from everstaff.core.config import FrameworkConfig
    from everstaff.core.secret_store import SecretStore
    from everstaff.protocols import FileStore, LLMClient, MemoryStore, TracingBackend
    from everstaff.sandbox.ipc.channel import IpcChannel


_EMBEDDER_API_KEY_MAP = {
    "openai": "OPENAI_API_KEY",
    "azure_openai": "AZURE_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "together": "TOGETHER_API_KEY",
}


class SandboxEnvironment(RuntimeEnvironment):
    """RuntimeEnvironment for sandbox processes.

    All infrastructure (memory, tracer, file store) is proxied over IPC
    to the orchestrator. LLM calls execute directly in sandbox.
    """

    def __init__(
        self,
        channel: "IpcChannel",
        secret_store: "SecretStore",
        workspace_dir: Path,
        config: "FrameworkConfig | None" = None,
    ) -> None:
        super().__init__(config=config)
        self._channel = channel
        self._secret_store = secret_store
        self._workspace_dir = workspace_dir

    def build_memory_store(self, max_tokens: int | None = None, **kwargs: Any) -> "MemoryStore":
        return ProxyMemoryStore(self._channel)

    def build_tracer(self, session_id: str = "") -> "TracingBackend":
        return ProxyTracer(self._channel)

    def build_file_store(self) -> "FileStore":
        return ProxyFileStore(self._channel)

    def build_llm_client(self, model: str, **kwargs: Any) -> "LLMClient":
        from everstaff.llm.litellm_client import LiteLLMClient
        return LiteLLMClient(model=model, **kwargs)

    def working_dir(self, session_id: str, root_session_id: str | None = None) -> Path:
        self._workspace_dir.mkdir(parents=True, exist_ok=True)
        return self._workspace_dir

    @property
    def secret_store(self) -> "SecretStore":
        return self._secret_store

    # --- mem0 integration (runs directly in sandbox, no IPC needed) ---

    def _get_or_create_mem0_client(self):
        if not hasattr(self, "_mem0_client"):
            from everstaff.memory.mem0_client import Mem0Client
            mem = self._config.memory
            llm_model_id = self._config.resolve_model(mem.llm_model_kind).model_id
            embed_model_id = self._config.resolve_model(mem.embedding_model_kind).model_id
            embed_provider, _ = Mem0Client._parse_embedding_model(embed_model_id)
            embedder_api_key = self._secret_store.get(
                _EMBEDDER_API_KEY_MAP.get(embed_provider, f"{embed_provider.upper()}_API_KEY")
            )
            self._mem0_client = Mem0Client(mem, llm_model_id, embed_model_id,
                                           embedder_api_key=embedder_api_key)
        return self._mem0_client

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

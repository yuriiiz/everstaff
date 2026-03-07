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

    def build_memory_store(self, max_tokens: int | None = None) -> "MemoryStore":
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

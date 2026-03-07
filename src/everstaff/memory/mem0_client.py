"""Thin async wrapper around the mem0 Python SDK."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from everstaff.core.config import MemoryConfig
    from everstaff.schema.model_config import ModelMapping

logger = logging.getLogger(__name__)

try:
    from mem0 import Memory
except ImportError:
    Memory = None  # type: ignore[assignment,misc]


class Mem0Client:
    """Async wrapper around mem0's synchronous Memory SDK.

    All blocking SDK calls are dispatched to a thread pool via asyncio.to_thread.
    """

    def __init__(self, config: "MemoryConfig", model_mapping: "ModelMapping") -> None:
        if Memory is None:
            raise ImportError(
                "mem0ai is required for memory integration. "
                "Install it with: pip install 'everstaff[mem0]'"
            )
        provider, model = self._parse_model_id(model_mapping.model_id)
        self._memory = Memory.from_config({
            "llm": {
                "provider": provider,
                "config": {"model": model},
            },
            "embedder": {
                "provider": provider,
                "config": {"model": config.embedding_model},
            },
            "vector_store": {
                "provider": config.vector_store,
                "config": {"path": config.vector_store_path},
            },
        })
        self._top_k = config.search_top_k
        self._threshold = config.search_threshold

    @staticmethod
    def _parse_model_id(model_id: str) -> tuple[str, str]:
        """Parse litellm format 'provider/model' into (provider, model)."""
        if "/" in model_id:
            provider, model = model_id.split("/", 1)
            return provider, model
        return "openai", model_id

    async def add(self, messages: list[dict], **scope: Any) -> list[dict]:
        """Extract memories from conversation messages."""
        kwargs = {k: v for k, v in scope.items() if v is not None}
        return await asyncio.to_thread(self._memory.add, messages, **kwargs)

    async def search(self, query: str, *, top_k: int | None = None, **scope: Any) -> list[dict]:
        """Retrieve relevant memories with threshold filtering."""
        kwargs = {k: v for k, v in scope.items() if v is not None}
        kwargs["limit"] = top_k or self._top_k
        results = await asyncio.to_thread(self._memory.search, query, **kwargs)
        return [r for r in results if r.get("score", 0) >= self._threshold]

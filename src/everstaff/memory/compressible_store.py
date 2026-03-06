from __future__ import annotations

from typing import Any

from everstaff.protocols import CompressionStrategy, MemoryStore, Message


def _estimate_tokens(messages: list[Message]) -> int:
    """Rough estimation: 1 token ≈ 4 chars."""
    chars = 0
    for m in messages:
        if m.content:
            chars += len(m.content)
        if m.tool_calls:
            chars += len(str(m.tool_calls))
    return chars // 4


_DEFAULT_MAX_TOKENS = 128_000
_COMPRESSION_RATIO = 0.7


class CompressibleMemoryStore:
    """Wraps any MemoryStore and applies compression before saving.

    Compression is triggered only when the estimated token count of the
    conversation history reaches ``compression_ratio × max_tokens``
    (default: 0.7 × 128 000 = 89 600 tokens).  The message-count
    threshold has been intentionally removed to avoid premature truncation
    on long multi-turn sessions.
    """

    def __init__(
        self,
        store: MemoryStore,
        strategy: CompressionStrategy,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
        compression_ratio: float = _COMPRESSION_RATIO,
    ) -> None:
        self._store = store
        self._strategy = strategy
        self._token_threshold = int(max_tokens * compression_ratio)

    def set_session_path(self, session_id: str, relpath: str) -> None:
        """Forward to inner store if it supports path overrides."""
        if hasattr(self._store, "set_session_path"):
            self._store.set_session_path(session_id, relpath)

    async def load(self, session_id: str) -> list[Message]:
        return await self._store.load(session_id)

    async def save(self, session_id: str, messages: list[Message], **kwargs: Any) -> None:
        """Save messages, compressing if needed. All extra kwargs forwarded to inner store."""
        if self._should_compress(messages):
            messages = await self._strategy.compress(messages)
        await self._store.save(session_id, messages, **kwargs)

    def _should_compress(self, messages: list[Message]) -> bool:
        return _estimate_tokens(messages) >= self._token_threshold

"""Knowledge backend protocol — the abstract interface for knowledge sources."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from everstaff.knowledge.models import SearchResult


@runtime_checkable
class KnowledgeBackend(Protocol):
    """Every knowledge backend implements this interface."""

    async def search(self, query: str, top_k: int = 5) -> SearchResult: ...

    async def list_sources(self) -> list[str]: ...

    async def get_document(self, source: str) -> str: ...

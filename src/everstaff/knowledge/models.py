"""Knowledge base data models."""

from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Any


class Chunk(BaseModel):
    """A chunk of content from a knowledge source."""

    content: str
    source: str  # file path or URL
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchResult(BaseModel):
    """Search results from everstaff.knowledge backends."""

    chunks: list[Chunk] = Field(default_factory=list)
    query: str = ""
    total_found: int = 0

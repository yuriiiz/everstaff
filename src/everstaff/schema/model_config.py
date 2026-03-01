"""Model mapping schema — maps logical model kinds to concrete LiteLLM model strings."""

from __future__ import annotations

from pydantic import BaseModel


class ModelMapping(BaseModel):
    """Maps a logical model kind to a concrete LiteLLM model string."""

    model_id: str
    max_tokens: int = 8192
    temperature: float = 0.7
    supports_tools: bool = True

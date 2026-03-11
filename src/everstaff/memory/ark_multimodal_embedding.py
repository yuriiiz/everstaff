"""Custom mem0 embedder for Volcengine/Ark multimodal embedding models.

These models only support the ``/embeddings/multimodal`` endpoint (not the
standard ``/embeddings``), so we bypass the OpenAI SDK and use httpx directly.
"""

from __future__ import annotations

import logging
import os
from typing import Literal, Optional

import httpx

from mem0.configs.embeddings.base import BaseEmbedderConfig
from mem0.embeddings.base import EmbeddingBase

logger = logging.getLogger(__name__)


class ArkMultimodalEmbedding(EmbeddingBase):
    """Embedding provider for Ark models that require ``/embeddings/multimodal``."""

    def __init__(self, config: Optional[BaseEmbedderConfig] = None):
        super().__init__(config)

        self.config.embedding_dims = self.config.embedding_dims or 2048

        self.api_key = self.config.api_key or os.getenv("OPENAI_API_KEY") or ""
        base_url = (
            self.config.openai_base_url
            or os.getenv("OPENAI_BASE_URL")
            or os.getenv("OPENAI_API_BASE")
            or "https://ark.cn-beijing.volces.com/api/v3"
        )
        # Ensure no trailing slash
        self._endpoint = f"{base_url.rstrip('/')}/embeddings/multimodal"
        self._client = httpx.Client(timeout=60)

    def embed(
        self,
        text: str,
        memory_action: Optional[Literal["add", "search", "update"]] = None,
    ) -> list:
        text = text.replace("\n", " ")
        payload = {
            "model": self.config.model,
            "input": [{"type": "text", "text": text}],
        }
        if self.config.embedding_dims:
            payload["encoding_format"] = "float"

        resp = self._client.post(
            self._endpoint,
            json=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        # Ark multimodal returns {"data": {"embedding": [...]}}
        # (not the standard OpenAI list format)
        payload = data["data"]
        if isinstance(payload, list):
            return payload[0]["embedding"]
        return payload["embedding"]

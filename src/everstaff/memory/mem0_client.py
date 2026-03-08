"""Thin async wrapper around the mem0 Python SDK."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from everstaff.core.config import MemoryConfig

logger = logging.getLogger(__name__)

FACT_EXTRACTION_PROMPT = """\
You are a Memory Organizer for an AI agent system.
Extract relevant facts from the conversation between the user and the assistant.

Focus on:
- User preferences, habits, and personal information
- Business facts, decisions, and conclusions reached
- Task outcomes and important results
- Domain knowledge learned during the conversation

Do NOT extract:
- System instructions, tool descriptions, or permission rules
- Agent internal state or configuration details
- Conversational filler ("hello", "thanks", "sure")

Here are some examples:

User: 我叫小明，我喜欢吃披萨
Assistant: 好的小明，记住了！
Output: {"facts": ["用户叫小明", "用户喜欢吃披萨"]}

User: Hi
Assistant: Hello! How can I help?
Output: {"facts": []}

User: Can you check my calendar for tomorrow?
Assistant: You have a meeting with John at 3pm about the Q2 report.
Output: {"facts": ["Has a meeting with John at 3pm about the Q2 report"]}

Return the extracted facts as a json object with a "facts" key containing a list of strings.
If no relevant facts are found, return {"facts": []}.
Detect the language of the conversation and record facts in the same language.
"""

try:
    import litellm
    from mem0 import Memory
except ImportError:
    litellm = None  # type: ignore[assignment]
    Memory = None  # type: ignore[assignment,misc]


class Mem0Client:
    """Async wrapper around mem0's synchronous Memory SDK.

    All blocking SDK calls are dispatched to a thread pool via asyncio.to_thread.
    """

    def __init__(
        self,
        config: "MemoryConfig",
        llm_model_id: str,
        embedding_model_id: str,
        embedder_api_key: str | None = None,
    ) -> None:
        if Memory is None:
            raise ImportError(
                "mem0ai is required for memory integration. "
                "Install it with: pip install 'everstaff[mem0]'"
            )
        embed_provider, embed_model = self._parse_embedding_model(embedding_model_id)
        embedder_config: dict = {"model": embed_model}
        if embedder_api_key:
            embedder_config["api_key"] = embedder_api_key
        # mem0's litellm provider passes top_p unconditionally, which some
        # newer models reject.  Setting drop_params lets litellm silently
        # strip unsupported parameters instead of raising.
        litellm.drop_params = True

        self._memory = Memory.from_config({
            "llm": {
                "provider": "litellm",
                "config": {"model": llm_model_id},
            },
            "embedder": {
                "provider": embed_provider,
                "config": embedder_config,
            },
            "vector_store": {
                "provider": config.vector_store,
                "config": {"path": config.vector_store_path},
            },
            "custom_fact_extraction_prompt": FACT_EXTRACTION_PROMPT,
        })
        self._top_k = config.search_top_k
        self._threshold = config.search_threshold

    @staticmethod
    def _parse_embedding_model(model_id: str) -> tuple[str, str]:
        """Parse embedding model string into (provider, model).

        If 'provider/model' format, extracts provider; otherwise defaults to 'openai'.
        """
        if "/" in model_id:
            provider, model = model_id.split("/", 1)
            return provider, model
        return "openai", model_id

    async def add(self, messages: list[dict], **scope: Any) -> list[dict]:
        """Extract memories from conversation messages."""
        kwargs = {k: v for k, v in scope.items() if v is not None}
        return await asyncio.to_thread(
            self._memory.add, messages, **kwargs
        )

    async def search(self, query: str, *, top_k: int | None = None, **scope: Any) -> list[dict]:
        """Retrieve relevant memories with threshold filtering."""
        kwargs = {k: v for k, v in scope.items() if v is not None}
        kwargs["limit"] = top_k or self._top_k
        response = await asyncio.to_thread(self._memory.search, query, **kwargs)
        results = response.get("results", []) if isinstance(response, dict) else response
        return [r for r in results if r.get("score", 0) >= self._threshold]

    async def get_all(self, *, limit: int = 100, **scope: Any) -> list[dict]:
        """List all memories matching the given scope."""
        kwargs = {k: v for k, v in scope.items() if v is not None}
        kwargs["limit"] = limit
        result = await asyncio.to_thread(self._memory.get_all, **kwargs)
        return result.get("results", []) if isinstance(result, dict) else result

from __future__ import annotations

import logging

from everstaff.protocols import Message

logger = logging.getLogger(__name__)


def _clean_orphan_tool_results(messages: list[Message]) -> list[Message]:
    """Remove leading tool-result messages whose assistant tool_call is missing.

    This preserves the invariant that every tool result has a preceding
    assistant message containing the matching tool_call id.
    """
    available_call_ids: set[str] = set()
    for m in messages:
        if m.role == "assistant" and m.tool_calls:
            for tc in m.tool_calls:
                call_id = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)
                if call_id:
                    available_call_ids.add(call_id)

    start = 0
    while start < len(messages):
        m = messages[start]
        if m.role == "tool" and m.tool_call_id and m.tool_call_id not in available_call_ids:
            logger.warning(
                "Dropping orphan tool result (tool_call_id=%s) "
                "whose assistant message was truncated away.",
                m.tool_call_id,
            )
            start += 1
        else:
            break

    return messages[start:]


class TruncationStrategy:
    """Keep the most recent `keep_last` messages.

    After slicing, any leading tool-result messages whose matching
    assistant tool_call was sliced away are also removed to preserve
    the invariant that every tool result has a preceding assistant
    message containing the matching tool_call id.
    """

    def __init__(self, keep_last: int = 20) -> None:
        self._keep_last = keep_last

    async def compress(self, messages: list[Message]) -> list[Message]:
        truncated = messages[-self._keep_last:]
        return _clean_orphan_tool_results(truncated)


class Mem0ExtractionStrategy:
    """Extract old messages to mem0, keep recent ones.

    On mem0 failure: fallback to plain truncation (log warning).
    """

    def __init__(
        self,
        mem0_client,
        *,
        user_id: str | None = None,
        agent_id: str | None = None,
        session_id: str | None = None,
        keep_last: int = 20,
    ) -> None:
        self._client = mem0_client
        self._user_id = user_id
        self._agent_id = agent_id
        self._session_id = session_id
        self._keep_last = keep_last

    async def compress(self, messages: list[Message]) -> list[Message]:
        if len(messages) <= self._keep_last:
            return messages

        old = messages[: -self._keep_last]
        recent = messages[-self._keep_last :]

        if old:
            chat_messages = [
                {"role": m.role, "content": m.content}
                for m in old
                if m.content
            ]
            if chat_messages:
                try:
                    scope: dict[str, str] = {}
                    if self._user_id:
                        scope["user_id"] = self._user_id
                    if self._agent_id:
                        scope["agent_id"] = self._agent_id
                    if self._session_id:
                        scope["run_id"] = self._session_id
                    await self._client.add(chat_messages, **scope)
                except Exception as exc:
                    logger.warning(
                        "Mem0ExtractionStrategy: mem0.add() failed, falling back to truncation: %s",
                        exc,
                    )

        return _clean_orphan_tool_results(recent)

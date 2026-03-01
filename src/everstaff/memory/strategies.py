from __future__ import annotations

import logging

from everstaff.protocols import Message

logger = logging.getLogger(__name__)


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

        # Build the set of tool_call ids that exist in the truncated window.
        available_call_ids: set[str] = set()
        for m in truncated:
            if m.role == "assistant" and m.tool_calls:
                for tc in m.tool_calls:
                    call_id = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)
                    if call_id:
                        available_call_ids.add(call_id)

        # Drop leading tool-result messages that reference a tool_call not
        # present in the truncated window (their assistant message was cut off).
        start = 0
        while start < len(truncated):
            m = truncated[start]
            if m.role == "tool" and m.tool_call_id and m.tool_call_id not in available_call_ids:
                logger.warning(
                    "TruncationStrategy: dropping orphan tool result (tool_call_id=%s) "
                    "whose assistant message was truncated away.",
                    m.tool_call_id,
                )
                start += 1
            else:
                break

        return truncated[start:]

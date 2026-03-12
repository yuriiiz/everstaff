from __future__ import annotations

import logging

from everstaff.protocols import Message

logger = logging.getLogger(__name__)

# Skill tool names whose results must be preserved across compaction.
_SKILL_TOOL_NAMES = frozenset({"use_skill", "read_skill_resource"})

_DEFAULT_MAX_TOKENS = 128_000
_TARGET_RATIO = 0.4  # compact to ~40% of max context window


def _estimate_tokens(messages: list[Message]) -> int:
    """Rough estimation: 1 token ~ 4 chars."""
    chars = 0
    for m in messages:
        if m.content:
            chars += len(m.content)
        if m.tool_calls:
            chars += len(str(m.tool_calls))
    return chars // 4


def _get_tool_call_id(tc) -> str | None:
    """Extract the id from a tool_call (dict or object)."""
    return tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)


def _get_tool_call_name(tc) -> str | None:
    """Extract the function name from a tool_call (dict or object)."""
    if isinstance(tc, dict):
        fn = tc.get("function", {})
        return fn.get("name") if isinstance(fn, dict) else getattr(fn, "name", None)
    fn = getattr(tc, "function", None)
    if fn is None:
        return None
    return fn.get("name") if isinstance(fn, dict) else getattr(fn, "name", None)


def _clean_orphan_tool_results(messages: list[Message]) -> list[Message]:
    """Remove tool-result messages whose assistant tool_call is missing.

    This preserves the invariant that every tool result has a preceding
    assistant message containing the matching tool_call id.

    Orphaned results can appear at any position (not just the leading edge)
    when context truncation removes an assistant message but its tool results
    are scattered across the conversation due to late arrival or duplication.
    """
    available_call_ids: set[str] = set()
    for m in messages:
        if m.role == "assistant" and m.tool_calls:
            for tc in m.tool_calls:
                call_id = _get_tool_call_id(tc)
                if call_id:
                    available_call_ids.add(call_id)

    cleaned: list[Message] = []
    for m in messages:
        if m.role == "tool" and m.tool_call_id and m.tool_call_id not in available_call_ids:
            logger.warning(
                "Dropping orphan tool result (tool_call_id=%s) "
                "whose assistant message was truncated away.",
                m.tool_call_id,
            )
            continue
        cleaned.append(m)

    return cleaned


def _ensure_complete_tool_groups(
    messages: list[Message],
    included: set[int],
    all_messages: list[Message],
) -> set[int]:
    """Ensure every included assistant tool_call has all its tool results,
    and every included tool result has its assistant message.

    Returns the expanded set of indices.
    """
    # Build mapping: tool_call_id -> (assistant_index, [tool_result_indices])
    call_id_to_assistant: dict[str, int] = {}
    call_id_to_results: dict[str, list[int]] = {}

    for idx, m in enumerate(all_messages):
        if m.role == "assistant" and m.tool_calls:
            for tc in m.tool_calls:
                cid = _get_tool_call_id(tc)
                if cid:
                    call_id_to_assistant[cid] = idx
        elif m.role == "tool" and m.tool_call_id:
            call_id_to_results.setdefault(m.tool_call_id, []).append(idx)

    expanded = set(included)
    changed = True
    while changed:
        changed = False
        for idx in list(expanded):
            m = all_messages[idx]
            if m.role == "assistant" and m.tool_calls:
                # Include all tool results for this assistant's tool_calls
                for tc in m.tool_calls:
                    cid = _get_tool_call_id(tc)
                    if cid and cid in call_id_to_results:
                        for ridx in call_id_to_results[cid]:
                            if ridx not in expanded:
                                expanded.add(ridx)
                                changed = True
            elif m.role == "tool" and m.tool_call_id:
                # Include the assistant message that issued this tool_call
                cid = m.tool_call_id
                if cid in call_id_to_assistant:
                    aidx = call_id_to_assistant[cid]
                    if aidx not in expanded:
                        expanded.add(aidx)
                        changed = True
                        # Adding the assistant may bring in more tool results
                        # on the next iteration

    return expanded


def _smart_compact(
    messages: list[Message],
    max_tokens: int,
    target_ratio: float = _TARGET_RATIO,
) -> list[Message]:
    """Smart compaction that preserves skill results and targets a token budget.

    1. Identify protected messages (skill tool_calls + their tool results).
    2. Build result from the end, adding messages until hitting the token budget.
    3. Always include protected messages even if they exceed the budget.
    4. Ensure complete tool call groups (assistant + all tool results).
    5. Clean orphans as a final safety net.
    """
    if not messages:
        return messages

    target_tokens = int(max_tokens * target_ratio)

    # --- Step 1: Identify protected indices (skill-related messages) ---
    protected: set[int] = set()

    for idx, m in enumerate(messages):
        if m.role == "assistant" and m.tool_calls:
            for tc in m.tool_calls:
                name = _get_tool_call_name(tc)
                if name in _SKILL_TOOL_NAMES:
                    protected.add(idx)
                    break  # one match is enough to protect the whole message

    # Expand protected set to include tool results of protected assistant messages
    # and assistant messages of protected tool results
    protected = _ensure_complete_tool_groups(messages, protected, messages)

    # --- Step 2: Build recent set from the end, respecting token budget ---
    # Subtract protected tokens from the budget so total stays near target.
    protected_tokens = sum(_estimate_tokens([messages[i]]) for i in protected)
    remaining_budget = max(target_tokens - protected_tokens, 0)

    recent: set[int] = set()
    recent_tokens = 0

    for idx in range(len(messages) - 1, -1, -1):
        if idx in protected:
            continue  # already counted in the protected budget
        m = messages[idx]
        m_tokens = _estimate_tokens([m])
        if recent_tokens + m_tokens > remaining_budget and recent:
            # We've hit the budget and already have some recent messages
            break
        recent.add(idx)
        recent_tokens += m_tokens

    # --- Step 3: Merge protected + recent ---
    included = protected | recent

    # --- Step 4: Ensure complete tool call groups ---
    included = _ensure_complete_tool_groups(messages, included, messages)

    # --- Step 5: Build result sorted by original index ---
    result = [messages[idx] for idx in sorted(included)]

    # --- Step 6: Final orphan cleanup ---
    result = _clean_orphan_tool_results(result)

    logger.info(
        "Smart compaction: %d -> %d messages (target=%d tokens, "
        "protected=%d skill messages, estimated=%d tokens)",
        len(messages),
        len(result),
        target_tokens,
        len(protected),
        _estimate_tokens(result),
    )

    return result


class TruncationStrategy:
    """Smart truncation strategy that preserves skill results.

    Instead of a fixed message count, targets ~40% of the context window
    after compaction, while always preserving skill-related messages
    (use_skill, read_skill_resource tool calls and their results).
    """

    def __init__(self, max_tokens: int = _DEFAULT_MAX_TOKENS) -> None:
        self._max_tokens = max_tokens

    async def compress(self, messages: list[Message]) -> list[Message]:
        return _smart_compact(messages, self._max_tokens)


class Mem0ExtractionStrategy:
    """Extract old messages to mem0, keep recent ones with smart compaction.

    Uses the same smart compaction logic as TruncationStrategy to determine
    which messages to keep. Old messages (those being dropped) are first
    sent to mem0 for long-term storage.

    On mem0 failure: fallback to smart compaction only (log warning).
    """

    def __init__(
        self,
        mem0_client,
        *,
        user_id: str | None = None,
        agent_id: str | None = None,
        session_id: str | None = None,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
    ) -> None:
        self._client = mem0_client
        self._user_id = user_id
        self._agent_id = agent_id
        self._session_id = session_id
        self._max_tokens = max_tokens

    async def compress(self, messages: list[Message]) -> list[Message]:
        # Compute what the compacted result will be
        compacted = _smart_compact(messages, self._max_tokens)

        # Determine which messages are being dropped (old messages)
        compacted_set = set(id(m) for m in compacted)
        old = [m for m in messages if id(m) not in compacted_set]

        # Send old messages to mem0 for long-term extraction
        if old:
            chat_messages = [
                {"role": m.role, "content": m.content}
                for m in old
                if m.content and m.role in ("user", "assistant")
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
                        "Mem0ExtractionStrategy: mem0.add() failed, "
                        "proceeding with compaction only: %s",
                        exc,
                    )

        return compacted

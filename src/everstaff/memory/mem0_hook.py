"""Mem0Hook — refreshes memory search before LLM calls, flushes on session end."""
from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from everstaff.protocols import HookContext, LLMResponse, Message, ToolResult

if TYPE_CHECKING:
    from everstaff.memory.mem0_client import Mem0Client
    from everstaff.memory.mem0_provider import Mem0Provider
    from everstaff.protocols import MemoryStore

logger = logging.getLogger(__name__)


class Mem0Hook:
    def __init__(
        self,
        mem0_provider: "Mem0Provider",
        mem0_client: "Mem0Client",
        memory_store: "MemoryStore",
        *,
        user_id: str | None = None,
        agent_id: str | None = None,
    ) -> None:
        self._provider = mem0_provider
        self._client = mem0_client
        self._memory = memory_store
        self._user_id = user_id
        self._agent_id = agent_id

    async def on_session_start(self, ctx: HookContext) -> None:
        pass

    async def on_session_end(self, ctx: HookContext, response: str) -> None:
        try:
            messages = await self._memory.load(ctx.session_id)
            chat_messages = [
                {"role": m.role, "content": m.content}
                for m in messages
                if m.content and m.role in ("user", "assistant")
            ]
            if chat_messages:
                scope: dict[str, Any] = {}
                if self._user_id:
                    scope["user_id"] = self._user_id
                if self._agent_id:
                    scope["agent_id"] = self._agent_id
                scope["run_id"] = ctx.session_id
                await self._client.add(chat_messages, **scope)
        except Exception as exc:
            logger.warning("Mem0Hook: session_end flush failed: %s", exc)

    async def on_user_input(self, ctx: HookContext, content: str) -> str:
        return content

    async def on_llm_start(
        self, ctx: HookContext, messages: list[Message]
    ) -> list[Message]:
        for m in reversed(messages):
            if m.role == "user" and m.content:
                logger.debug("Mem0Hook.on_llm_start: query=%s", m.content[:100])
                self._provider.set_query(m.content)
                break
        else:
            logger.debug("Mem0Hook.on_llm_start: no user message found, skipping")
            return messages
        await self._provider.refresh()
        injection = self._provider.get_prompt_injection()
        logger.debug("Mem0Hook.on_llm_start: injection length=%d", len(injection))
        return messages

    async def on_llm_end(
        self, ctx: HookContext, response: LLMResponse
    ) -> LLMResponse:
        return response

    async def on_tool_start(
        self, ctx: HookContext, args: dict, tool_name: str
    ) -> dict:
        return args

    async def on_tool_end(
        self, ctx: HookContext, result: ToolResult, tool_name: str
    ) -> ToolResult:
        return result

    async def on_subagent_start(
        self, ctx: HookContext, agent_name: str, prompt: str
    ) -> str:
        return prompt

    async def on_subagent_end(
        self, ctx: HookContext, agent_name: str, result: str
    ) -> None:
        pass

    async def on_memory_compact(
        self,
        ctx: HookContext,
        before: list[Message],
        after: list[Message],
    ) -> None:
        pass

    async def on_error(
        self, ctx: HookContext, error: Exception, phase: str
    ) -> None:
        pass

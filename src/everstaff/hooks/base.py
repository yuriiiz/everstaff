"""BaseHook — no-op default implementations. Subclass and override what you need."""
from __future__ import annotations

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from everstaff.protocols import HookContext, LLMResponse, Message, ToolResult


class BaseHook:
    async def on_session_start(self, ctx: HookContext) -> None:
        pass

    async def on_session_end(self, ctx: HookContext, response: str) -> None:
        pass

    async def on_user_input(self, ctx: HookContext, content: str) -> str:
        return content

    async def on_llm_start(self, ctx: HookContext, messages: list[Message]) -> list[Message]:
        return messages

    async def on_llm_end(self, ctx: HookContext, response: LLMResponse) -> LLMResponse:
        return response

    async def on_tool_start(self, ctx: HookContext, args: dict, tool_name: str) -> dict:
        """Called before tool execution. Return (possibly modified) args dict.
        Note: args comes before tool_name (args is the mutable return value)."""
        return args

    async def on_tool_end(self, ctx: HookContext, result: ToolResult, tool_name: str) -> ToolResult:
        """Called after tool execution. Return (possibly modified) result.
        Note: result comes before tool_name (result is the mutable return value)."""
        return result

    async def on_subagent_start(self, ctx: HookContext, agent_name: str, prompt: str) -> str:
        return prompt

    async def on_subagent_end(self, ctx: HookContext, agent_name: str, result: str) -> None:
        pass

    async def on_memory_compact(self, ctx: HookContext, before: list[Message], after: list[Message]) -> None:
        pass

    async def on_error(self, ctx: HookContext, error: Exception, phase: str) -> None:
        pass

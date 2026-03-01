"""Built-in pipeline stages: PermissionStage, ExecutionStage."""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from everstaff.tools.pipeline import ToolCallContext
from everstaff.protocols import PermissionChecker, ToolRegistry, ToolResult


class PermissionStage:
    """Checks permissions before calling next. Blocks if denied."""

    def __init__(self, checker: PermissionChecker) -> None:
        self._checker = checker

    async def __call__(
        self,
        ctx: ToolCallContext,
        next: Callable[[ToolCallContext], Awaitable[ToolResult]],
    ) -> ToolResult:
        result = self._checker.check(ctx.tool_name, ctx.args)
        if not result.allowed:
            return ToolResult(
                tool_call_id=ctx.tool_call_id,
                content=f"Permission denied for '{ctx.tool_name}': {result.reason}",
                is_error=True,
            )
        return await next(ctx)


class ExecutionStage:
    """Terminal stage: calls ToolRegistry.execute()."""

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    async def __call__(
        self,
        ctx: ToolCallContext,
        _next: Callable[[ToolCallContext], Awaitable[ToolResult]],
    ) -> ToolResult:
        return await self._registry.execute(ctx.tool_name, ctx.args, ctx.tool_call_id)

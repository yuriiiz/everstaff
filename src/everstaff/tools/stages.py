"""Built-in pipeline stages: PermissionStage, ExecutionStage."""
from __future__ import annotations

from typing import Any, Awaitable, Callable
from uuid import uuid4

from everstaff.tools.pipeline import ToolCallContext
from everstaff.protocols import (
    HitlRequest,
    HumanApprovalRequired,
    PermissionChecker,
    ToolRegistry,
    ToolResult,
)


def _format_tool_prompt(tool_name: str, args: dict) -> str:
    """Format a tool call description with argument-level detail."""
    if not args:
        return f"Agent wants to execute: {tool_name}()"

    # Single-argument tool: compact format
    if len(args) == 1:
        _key, val = next(iter(args.items()))
        val_str = str(val)
        if len(val_str) > 200:
            val_str = val_str[:200] + "..."
        return f"Agent wants to execute: {tool_name}({val_str})"

    # Multi-argument: key=value format
    parts = []
    for k, v in args.items():
        v_str = str(v)
        if len(v_str) > 100:
            v_str = v_str[:100] + "..."
        parts.append(f"{k}={v_str}")
    return f"Agent wants to execute: {tool_name}({', '.join(parts)})"


class PermissionStage:
    """Checks permissions before calling next.

    - Denied → return error ToolResult
    - Needs HITL → raise HumanApprovalRequired with tool_permission request
    - Allowed → call next
    """

    def __init__(self, checker: PermissionChecker) -> None:
        self._checker = checker

    async def __call__(
        self,
        ctx: ToolCallContext,
        next: Callable[[ToolCallContext], Awaitable[ToolResult]],
    ) -> ToolResult:
        result = self._checker.check(ctx.tool_name, ctx.args)

        if not result.allowed and not result.needs_hitl:
            return ToolResult(
                tool_call_id=ctx.tool_call_id,
                content=f"Permission denied for '{ctx.tool_name}': {result.reason}",
                is_error=True,
            )

        if result.needs_hitl:
            request = HitlRequest(
                hitl_id=str(uuid4()),
                type="tool_permission",
                prompt=_format_tool_prompt(ctx.tool_name, ctx.args),
                tool_name=ctx.tool_name,
                tool_args=ctx.args,
                tool_call_id=ctx.tool_call_id,
                options=["reject", "approve_once", "approve_session", "approve_permanent"],
            )
            raise HumanApprovalRequired([request])

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

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


def _build_tool_permission_options(tool_name: str, args: dict, tool_registry) -> list[dict[str, str]]:
    """Build structured permission options with pattern granularity.

    Returns a list of dicts with keys: id, label, scope, pattern.
    """
    # Try to get a permission hint from the tool
    hint = None
    try:
        tool_instance = tool_registry._tools.get(tool_name) if tool_registry else None
        if tool_instance and hasattr(tool_instance, "permission_hint"):
            hint = tool_instance.permission_hint(args)
    except Exception:
        pass

    options: list[dict[str, str]] = []

    # Reject
    options.append({"id": "reject", "label": "Reject", "scope": "", "pattern": ""})

    # Allow Once (no pattern stored, just this specific invocation)
    options.append({"id": "approve_once", "label": "Allow Once", "scope": "once", "pattern": ""})

    if hint and hint.suggested_pattern and hint.suggested_pattern != "*":
        # Narrow pattern: e.g. Bash(ls *)
        narrow_pat = f"{tool_name}({hint.suggested_pattern})"
        narrow_label_short = f"{tool_name}({hint.suggested_pattern})"
        options.append({
            "id": "approve_session_narrow",
            "label": f"Allow {narrow_label_short} for Session",
            "scope": "session",
            "pattern": narrow_pat,
        })

    # Broad: allow all invocations of this tool for session
    options.append({
        "id": "approve_session",
        "label": f"Allow all {tool_name} for Session",
        "scope": "session",
        "pattern": tool_name,
    })

    if hint and hint.suggested_pattern and hint.suggested_pattern != "*":
        narrow_pat = f"{tool_name}({hint.suggested_pattern})"
        narrow_label_short = f"{tool_name}({hint.suggested_pattern})"
        options.append({
            "id": "approve_permanent_narrow",
            "label": f"Always Allow {narrow_label_short}",
            "scope": "permanent",
            "pattern": narrow_pat,
        })

    # Broad: always allow all invocations of this tool
    options.append({
        "id": "approve_permanent",
        "label": f"Always Allow all {tool_name}",
        "scope": "permanent",
        "pattern": tool_name,
    })

    return options


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
            # Get tool registry from agent context for permission hints
            tool_registry = getattr(ctx.agent_context, "tool_registry", None)
            perm_options = _build_tool_permission_options(ctx.tool_name, ctx.args, tool_registry)

            request = HitlRequest(
                hitl_id=str(uuid4()),
                type="tool_permission",
                prompt=_format_tool_prompt(ctx.tool_name, ctx.args),
                tool_name=ctx.tool_name,
                tool_args=ctx.args,
                tool_call_id=ctx.tool_call_id,
                options=["reject", "approve_once", "approve_session", "approve_permanent"],
                tool_permission_options=perm_options,
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

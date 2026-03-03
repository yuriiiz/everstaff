"""ToolCallPipeline — executes a tool call through a sequence of stages."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from everstaff.protocols import ToolResult

if TYPE_CHECKING:
    from everstaff.core.context import AgentContext


@dataclass
class ToolCallContext:
    tool_name: str
    args: dict[str, Any]
    agent_context: AgentContext
    tool_call_id: str
    metadata: dict[str, Any] = field(default_factory=dict)
    permission_checked: bool = False


StageCallable = Callable[
    [ToolCallContext, Callable[[ToolCallContext], Awaitable[ToolResult]]],
    Awaitable[ToolResult],
]


class ToolCallPipeline:
    """Runs a tool call through stages in order. Last stage must be ExecutionStage."""

    def __init__(self, stages: list[StageCallable]) -> None:
        self._stages = list(stages)

    async def check_permission(self, ctx: ToolCallContext) -> ToolResult | None:
        """Run only the PermissionStage (first stage) to check permissions early.

        Returns None if permission is granted (caller should proceed).
        Returns a ToolResult if permission is denied (caller should use it as the result).
        Raises HumanApprovalRequired if HITL approval is needed.

        If the pipeline has no PermissionStage (first stage is not a permission
        checker), returns None immediately (no permission check needed).
        """
        if not self._stages:
            return None

        from everstaff.tools.stages import PermissionStage
        stage = self._stages[0]
        if not isinstance(stage, PermissionStage):
            # No permission stage in pipeline — skip early check
            return None

        async def passthrough(ctx: ToolCallContext) -> ToolResult:
            # Permission granted — signal via sentinel
            return ToolResult(tool_call_id=ctx.tool_call_id, content="__permission_granted__")

        result = await stage(ctx, passthrough)
        if result.content == "__permission_granted__":
            ctx.permission_checked = True
            return None  # permission granted
        return result  # permission denied

    async def execute(self, ctx: ToolCallContext) -> ToolResult:
        start_index = 1 if ctx.permission_checked else 0

        async def _run(index: int, ctx: ToolCallContext) -> ToolResult:
            if index >= len(self._stages):
                return ToolResult(
                    tool_call_id=ctx.tool_call_id,
                    content="No terminal stage in pipeline",
                    is_error=True,
                )
            stage = self._stages[index]

            async def next_fn(ctx: ToolCallContext) -> ToolResult:
                return await _run(index + 1, ctx)

            return await stage(ctx, next_fn)

        return await _run(start_index, ctx)

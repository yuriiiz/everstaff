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


StageCallable = Callable[
    [ToolCallContext, Callable[[ToolCallContext], Awaitable[ToolResult]]],
    Awaitable[ToolResult],
]


class ToolCallPipeline:
    """Runs a tool call through stages in order. Last stage must be ExecutionStage."""

    def __init__(self, stages: list[StageCallable]) -> None:
        self._stages = list(stages)

    async def execute(self, ctx: ToolCallContext) -> ToolResult:
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

        return await _run(0, ctx)

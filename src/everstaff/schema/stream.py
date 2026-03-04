"""StreamEvent types emitted by AgentRuntime.run_stream()."""
from __future__ import annotations
from typing import Any, Literal, Annotated, Union

from pydantic import BaseModel, Field


class TextDelta(BaseModel):
    type: Literal["text_delta"] = "text_delta"
    content: str


class ThinkingDelta(BaseModel):
    type: Literal["thinking_delta"] = "thinking_delta"
    content: str


class ToolCallStart(BaseModel):
    type: Literal["tool_call_start"] = "tool_call_start"
    name: str
    args: dict[str, Any]


class ToolCallEnd(BaseModel):
    type: Literal["tool_call_end"] = "tool_call_end"
    name: str
    result: str
    is_error: bool = False


class TurnStart(BaseModel):
    type: Literal["turn_start"] = "turn_start"
    turn: int


class SessionEnd(BaseModel):
    type: Literal["session_end"] = "session_end"
    response: str


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    error: str


class HitlRequestEvent(BaseModel):
    type: Literal["hitl_request"] = "hitl_request"
    hitl_id: str
    session_id: str
    prompt: str
    hitl_type: str          # "approve_reject" | "choose" | "provide_input" | "tool_permission"
    options: list[str] = []
    context: str = ""
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    tool_call_id: str = ""
    # Structured permission options with pattern granularity
    tool_permission_options: list[dict[str, str]] = []


class HitlResolvedEvent(BaseModel):
    type: Literal["hitl_resolved"] = "hitl_resolved"
    hitl_id: str
    decision: str
    resolved_by: str


class TokenUsageEvent(BaseModel):
    type: Literal["token_usage"] = "token_usage"
    model_id: str
    input_tokens: int
    output_tokens: int


class FileCreatedEvent(BaseModel):
    type: Literal["file_created"] = "file_created"
    file_path: str      # relative to workspace, e.g. "output/report.md"
    file_name: str      # basename, e.g. "report.md"
    size: int           # bytes
    mime_type: str       # e.g. "text/markdown", "image/png"


# Union with discriminator for clean OpenAPI oneOf
StreamEvent = Annotated[
    Union[
        TextDelta,
        ThinkingDelta,
        ToolCallStart,
        ToolCallEnd,
        TurnStart,
        SessionEnd,
        ErrorEvent,
        HitlRequestEvent,
        HitlResolvedEvent,
        TokenUsageEvent,
        FileCreatedEvent,
    ],
    Field(discriminator="type"),
]

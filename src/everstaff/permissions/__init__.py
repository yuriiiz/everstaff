"""Permission system — tool call allow/deny rules."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PermissionConfig(BaseModel):
    """Permission configuration with allow and deny lists.

    Rules use the format: ToolName(argument_pattern)
    - ToolName        — matches the tool with any arguments
    - ToolName(*)     — same as above
    - ToolName()      — matches only calls with no arguments
    - ToolName(foo:*) — glob match against canonical argument string
    """

    allow: list[str] = Field(default_factory=list)
    deny: list[str] = Field(default_factory=list)
    require_approval: list[str] = Field(default_factory=list)


__all__ = ["PermissionConfig"]

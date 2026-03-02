"""Permission system — tool call allow/deny rules."""

from __future__ import annotations

import warnings
from enum import Enum

from pydantic import BaseModel, Field, model_validator


class PermissionGrantScope(str, Enum):
    """Grant scope for tool permission HITL approvals."""
    ONCE = "once"
    SESSION = "session"
    PERMANENT = "permanent"


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

    @model_validator(mode="after")
    def _deprecate_require_approval(self) -> "PermissionConfig":
        if self.require_approval:
            warnings.warn(
                "PermissionConfig.require_approval is deprecated and will be removed. "
                "Tools not in the allow list now automatically trigger HITL approval.",
                DeprecationWarning,
                stacklevel=4,
            )
            self.require_approval = []
        return self


__all__ = ["PermissionConfig", "PermissionGrantScope"]

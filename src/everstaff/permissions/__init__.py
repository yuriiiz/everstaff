"""Permission system — tool call allow/deny rules."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class PermissionGrantScope(str, Enum):
    """Grant scope for tool permission HITL approvals."""
    ONCE = "once"
    SESSION = "session"
    PERMANENT = "permanent"


class PermissionConfig(BaseModel):
    """Permission configuration with allow and deny lists.

    Pattern syntax (fnmatch glob):
        ToolName            — matches the tool with any arguments
        ToolName(*)         — same as above (explicit wildcard)
        ToolName(ls *)      — shorthand: glob-matched against every string arg value
        ToolName(command:ls *) — explicit key: glob-matched against only that arg

    Tools not in the allow list automatically trigger HITL approval.
    """

    allow: list[str] = Field(default_factory=list)
    deny: list[str] = Field(default_factory=list)


__all__ = ["PermissionConfig", "PermissionGrantScope"]

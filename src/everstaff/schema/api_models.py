from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from everstaff.schema.token_stats import TokenUsage


class AgentMetadata(BaseModel):
    name: str
    version: str = "0.1.0"
    description: str = ""
    avatar_url: Optional[str] = None
    skills: list[str] = []
    tools: list[str] = []
    model: str = ""


class SessionMetadata(BaseModel):
    """Typed metadata stored within a Session."""
    title: str = ""
    own_calls: list[TokenUsage] = Field(default_factory=list)
    children_calls: list[TokenUsage] = Field(default_factory=list)
    tool_calls_count: int = 0
    errors_count: int = 0
    system_prompt: Optional[str] = None


class HitlResolution(BaseModel):
    """Typed HITL resolution — replaces dict-based response field."""
    decision: str
    comment: Optional[str] = None
    resolved_at: datetime
    resolved_by: str = "human"
    grant_scope: Optional[str] = None  # "once" | "session" | "permanent"
    permission_pattern: Optional[str] = None  # e.g. "Bash(ls *)", "Bash"


class ErrorResponse(BaseModel):
    """Standard error envelope for all API error responses."""
    error: str
    detail: Optional[str] = None


class CreateSessionRequest(BaseModel):
    agent_name: str
    resume_session_id: Optional[str] = None


class CreateSessionResponse(BaseModel):
    session_id: str
    created_at: str


class UserMessageRequest(BaseModel):
    role: str = "user"
    content: str


class UpdateToolCodeRequest(BaseModel):
    code: str


class CreateToolRequest(BaseModel):
    name: str
    description: str
    code: Optional[str] = None

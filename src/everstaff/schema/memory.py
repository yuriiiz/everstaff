"""Memory schema models for session storage."""
from __future__ import annotations

from pydantic import BaseModel, Field

from everstaff.schema.token_stats import TokenUsage  # noqa: F401  (canonical, re-exported)
from everstaff.schema.api_models import SessionMetadata
from everstaff.protocols import Message


class Session(BaseModel):
    session_id: str
    parent_session_id: str | None = None
    agent_name: str = ""
    agent_uuid: str | None = None
    created_at: str
    updated_at: str
    status: str = "running"
    active: bool = False
    messages: list[Message] = Field(default_factory=list)
    metadata: SessionMetadata = Field(default_factory=SessionMetadata)
    hitl_requests: list[dict] = Field(default_factory=list)

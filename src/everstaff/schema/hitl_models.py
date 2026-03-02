"""Typed models for HITL request/response records stored in session.json."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from everstaff.schema.api_models import HitlResolution


class HitlRequestPayload(BaseModel):
    """The agent's request details."""
    type: str               # approve_reject | choose | provide_input | notify | tool_permission
    prompt: str
    options: list[str] = Field(default_factory=list)
    context: str = ""
    tool_name: str = ""
    tool_args: dict[str, Any] = Field(default_factory=dict)


class HitlRequestRecord(BaseModel):
    """Full HITL record as stored in session.json hitl_requests array."""
    hitl_id: str
    tool_call_id: str = ""
    created_at: str = ""
    timeout_seconds: int = 86400
    status: str = "pending"            # pending | resolved | expired
    origin_session_id: str = ""
    origin_agent_name: str = ""
    request: HitlRequestPayload
    response: Optional[HitlResolution] = None

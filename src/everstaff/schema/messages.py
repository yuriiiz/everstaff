"""Conversation message types."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field
from typing import Any


class ToolCallRequest(BaseModel):
    """An LLM-requested tool call."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolCallResult(BaseModel):
    """Result of executing a tool."""

    tool_call_id: str
    name: str
    content: str
    is_error: bool = False


class Message(BaseModel):
    """A single message in the conversation."""

    role: str  # "system", "user", "assistant", "tool"
    content: str | None = None
    tool_calls: list[ToolCallRequest] = Field(default_factory=list)
    tool_call_id: str | None = None
    name: str | None = None
    pinned: bool = False  # pinned messages are never dropped by context window manager


def dicts_to_messages(dicts: list[dict]) -> list[Message]:
    """Convert OpenAI/LiteLLM format message dicts to Message objects.

    Handles the conversion of tool_calls from the OpenAI dict format
    (with nested ``function`` key and JSON-string arguments) into
    :class:`ToolCallRequest` objects.
    """
    import json as _json

    messages: list[Message] = []
    for d in dicts:
        role = d.get("role", "")
        content = d.get("content")
        tool_call_id = d.get("tool_call_id")
        name = d.get("name")

        tool_calls: list[ToolCallRequest] = []
        for tc in d.get("tool_calls", []):
            func = tc.get("function", {})
            args_raw = func.get("arguments", "{}")
            if isinstance(args_raw, str):
                try:
                    args = _json.loads(args_raw)
                except _json.JSONDecodeError:
                    import ast as _ast
                    try:
                        args = _ast.literal_eval(args_raw)
                    except Exception:
                        args = {"raw": args_raw}
            else:
                args = args_raw
            tool_calls.append(ToolCallRequest(
                id=tc.get("id", ""),
                name=func.get("name", ""),
                arguments=args,
            ))

        messages.append(Message(
            role=role,
            content=content,
            tool_calls=tool_calls,
            tool_call_id=tool_call_id,
            name=name,
        ))
    return messages

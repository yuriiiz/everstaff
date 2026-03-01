"""Unified tool definition models used across native, MCP, and skill tools."""

from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Any


class ToolParameter(BaseModel):
    """A single parameter for a tool."""

    name: str
    type: str  # JSON Schema type: "string", "integer", "boolean", "number", "array", "object"
    description: str = ""
    required: bool = True
    default: Any = None


class ToolDefinition(BaseModel):
    """Unified tool definition used by all tool sources."""

    name: str
    description: str = ""
    parameters: list[ToolParameter] = Field(default_factory=list)
    source: str = "native"  # "native", "mcp", "builtin"
    mcp_server_name: str | None = None
    strict: bool = False
    json_schema: dict | None = None

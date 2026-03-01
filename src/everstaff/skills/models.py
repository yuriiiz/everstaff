"""Skill metadata and content models."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field


class SkillMetadata(BaseModel):
    """Level 1: lightweight metadata parsed from SKILL.md frontmatter."""

    name: str
    description: str
    path: Path


class SkillContent(BaseModel):
    """Level 2: full skill content loaded on demand."""

    metadata: SkillMetadata
    instructions: str
    resource_files: list[Path] = Field(default_factory=list)

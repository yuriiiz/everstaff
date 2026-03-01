"""Autonomy configuration models for daemon-driven agents."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class HitlChannelRef(BaseModel):
    model_config = ConfigDict(extra="allow")

    ref: str

    def overrides(self) -> dict:
        return {k: v for k, v in (self.model_extra or {}).items()}


class TriggerConfig(BaseModel):
    id: str
    type: str  # "cron" | "interval"
    schedule: str = ""        # cron expression (type=cron)
    every: int = 0            # seconds (type=interval)
    task: str = ""            # task description for cron/interval
    hitl_channels: list[HitlChannelRef] | None = None


class GoalConfig(BaseModel):
    id: str
    description: str
    success_criteria: str = ""
    priority: str = "normal"  # "high" | "normal" | "low"


class AutonomyConfig(BaseModel):
    enabled: bool = False
    level: str = "supervised"
    # "autonomous"    — runs fully independently; no human notification
    # "supervised"    — executes tasks, then notifies humans after completion (default)
    # "collaborative" — requires human approval before executing each action
    tick_interval: int = 3600
    max_instances: int = 1
    instance_strategy: str = "queue"  # "queue" | "parallel" | "replace"
    think_model: str = "fast"
    act_model: str = "smart"
    triggers: list[TriggerConfig] = Field(default_factory=list)
    goals: list[GoalConfig] = Field(default_factory=list)

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
    type: str  # "cron" | "interval" | "webhook" | "file_watch" | "internal"
    schedule: str = ""        # cron expression (type=cron)
    every: int = 0            # seconds (type=interval)
    task: str = ""            # task description for cron/interval
    # file_watch
    watch_paths: list[str] = Field(default_factory=list)
    # internal
    condition: str = ""         # "episode_count" | "goal_stale" | "error_rate"
    threshold: int = 5          # minimum threshold before firing


class GoalConfig(BaseModel):
    id: str
    description: str
    success_criteria: str = ""
    priority: str = "normal"  # "high" | "normal" | "low"


class AutonomyConfig(BaseModel):
    enabled: bool = False
    tick_interval: int = 3600
    max_instances: int = 1
    instance_strategy: str = "queue"  # "queue" | "parallel" | "replace"
    think_model: str = "fast"
    act_model: str = "smart"
    triggers: list[TriggerConfig] = Field(default_factory=list)
    goals: list[GoalConfig] = Field(default_factory=list)

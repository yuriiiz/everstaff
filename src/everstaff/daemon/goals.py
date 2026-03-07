"""Goal breakdown models for daemon long-term goal management."""
from __future__ import annotations

from pydantic import BaseModel, Field


class SubGoal(BaseModel):
    description: str
    acceptance_criteria: str = ""
    status: str = "pending"  # "pending" | "in_progress" | "completed" | "blocked"
    progress_note: str = ""


class GoalBreakdown(BaseModel):
    """Daemon-maintained breakdown of a user-defined GoalConfig."""
    goal_id: str
    sub_goals: list[SubGoal] = Field(default_factory=list)

    @property
    def completion_ratio(self) -> float:
        if not self.sub_goals:
            return 0.0
        completed = sum(1 for sg in self.sub_goals if sg.status == "completed")
        return completed / len(self.sub_goals)

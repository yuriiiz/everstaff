"""Token usage and cost tracking models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TokenUsage(BaseModel):
    """Token usage for a single LLM call."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    model_id: str = ""


class ModelStats(BaseModel):
    """Aggregate stats for a specific model."""

    calls: list[TokenUsage] = Field(default_factory=list)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0


class SessionStats(BaseModel):
    """Aggregate stats for an entire agent session."""

    models: dict[str, ModelStats] = Field(default_factory=dict)
    own_calls: list[TokenUsage] = Field(default_factory=list)
    children_calls: list[TokenUsage] = Field(default_factory=list)
    tool_calls_count: int = 0
    errors_count: int = 0

    @property
    def model_calls_dicts(self) -> list[dict[str, Any]]:
        return [
            {
                "model_id": call.model_id,
                "input_token": call.input_tokens,
                "output_token": call.output_tokens,
                "total_token": call.total_tokens
            }
            for call in self.own_calls
        ]

    @property
    def children_model_calls_dicts(self) -> list[dict[str, Any]]:
        return [
            {
                "model_id": call.model_id,
                "input_token": call.input_tokens,
                "output_token": call.output_tokens,
                "total_token": call.total_tokens
            }
            for call in self.children_calls
        ]

    @property
    def calls(self) -> list[dict[str, Any]]:
        return self.model_calls_dicts

    @property
    def total_input_tokens(self) -> int:
        return sum(m.total_input_tokens for m in self.models.values())

    @property
    def total_output_tokens(self) -> int:
        return sum(m.total_output_tokens for m in self.models.values())

    @property
    def total_tokens(self) -> int:
        return sum(m.total_tokens for m in self.models.values())

    def record(self, usage: TokenUsage) -> None:
        model = getattr(usage, "model_id", "unknown")
        if model not in self.models:
            self.models[model] = ModelStats()
            
        m_stats = self.models[model]
        m_stats.calls.append(usage)
        m_stats.total_input_tokens += usage.input_tokens
        m_stats.total_output_tokens += usage.output_tokens
        m_stats.total_tokens += usage.total_tokens
        
        self.own_calls.append(usage)

    def record_tool_call(self) -> None:
        self.tool_calls_count += 1

    def record_error(self) -> None:
        self.errors_count += 1

    def merge(self, other: SessionStats) -> None:
        """Merge another session's stats into this one (for sub-agent aggregation)."""
        for model_id, m_stats in other.models.items():
            if model_id not in self.models:
                self.models[model_id] = ModelStats()
            
            self.models[model_id].calls.extend(m_stats.calls)
            self.models[model_id].total_input_tokens += m_stats.total_input_tokens
            self.models[model_id].total_output_tokens += m_stats.total_output_tokens
            self.models[model_id].total_tokens += m_stats.total_tokens

        self.children_calls.extend(other.own_calls)
        self.children_calls.extend(other.children_calls)

        self.tool_calls_count += other.tool_calls_count
        self.errors_count += other.errors_count

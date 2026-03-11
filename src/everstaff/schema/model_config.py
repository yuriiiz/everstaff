"""Model mapping schema — maps logical model kinds to concrete LiteLLM model strings."""

from __future__ import annotations

from pydantic import BaseModel


class ModelMapping(BaseModel):
    """Maps a logical model kind to a concrete LiteLLM model string."""

    model_id: str
    max_tokens: int = 128000     # context window size (used for compression threshold, UI display)
    max_output_tokens: int = 8192  # max tokens the LLM may generate per response
    temperature: float = 0.7
    supports_tools: bool = True
    timeout: int = 120           # seconds before LLM API call times out
    max_retries: int = 2         # number of retries on timeout/transient errors
    stream_chunk_timeout: int = 300  # seconds to wait for each streaming chunk before treating as stalled
    stream_total_timeout: int = 600  # total wall-clock seconds for the entire streaming call
    tpm_limit: int | None = None     # tokens per minute limit; None = unlimited
    rpm_limit: int | None = None     # requests per minute limit; None = unlimited

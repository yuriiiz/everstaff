"""Config API — read-only endpoints for current framework configuration."""
from __future__ import annotations

from fastapi import APIRouter

# Key name substrings (case-insensitive) whose values should be redacted.
_SENSITIVE_PATTERNS = ("secret", "password", "token", "_key", "api_key")
_REDACTED = "***"


def _is_sensitive(key: str) -> bool:
    k = key.lower()
    return any(p in k for p in _SENSITIVE_PATTERNS)


def _mask_secrets(obj: object) -> object:
    """Recursively redact string values whose key looks like a secret."""
    if isinstance(obj, dict):
        return {
            k: _REDACTED if (_is_sensitive(k) and isinstance(v, str) and v)
            else _mask_secrets(v)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_mask_secrets(item) for item in obj]
    return obj


def make_router(config) -> APIRouter:
    router = APIRouter(tags=["config"], prefix="/config")

    @router.get("")
    async def get_config() -> dict:
        """Return current framework configuration with secrets redacted."""
        raw = config.model_dump(by_alias=True, exclude_none=True)
        return _mask_secrets(raw)

    @router.get("/models")
    async def get_models() -> dict:
        """Return model kind -> mapping for all configured model kinds."""
        mappings = config.model_mappings
        return {
            kind: {
                "model_id": m.model_id,
                "max_tokens": m.max_tokens,
                "max_output_tokens": m.max_output_tokens,
                "temperature": m.temperature,
                "supports_tools": m.supports_tools,
            }
            for kind, m in mappings.items()
        }

    return router

"""Ephemeral token store for sandbox authentication."""
from __future__ import annotations

import secrets
import time


class _TokenEntry:
    __slots__ = ("session_id", "created_at", "ttl_seconds", "consumed")

    def __init__(self, session_id: str, ttl_seconds: float) -> None:
        self.session_id = session_id
        self.created_at = time.monotonic()
        self.ttl_seconds = ttl_seconds
        self.consumed = False

    def is_valid(self) -> bool:
        if self.consumed:
            return False
        return (time.monotonic() - self.created_at) < self.ttl_seconds


class EphemeralTokenStore:
    """Manages single-use, TTL-based tokens for sandbox authentication."""

    def __init__(self) -> None:
        self._tokens: dict[str, _TokenEntry] = {}

    def create(self, session_id: str, ttl_seconds: float = 30.0) -> str:
        """Create a new ephemeral token for the given session."""
        token = secrets.token_urlsafe(32)
        self._tokens[token] = _TokenEntry(session_id, ttl_seconds)
        return token

    def validate_and_consume(self, token: str) -> str | None:
        """Validate token and consume it. Returns session_id if valid, None otherwise."""
        entry = self._tokens.get(token)
        if entry is None or not entry.is_valid():
            return None
        entry.consumed = True
        return entry.session_id

    def cleanup_expired(self) -> None:
        """Remove expired or consumed tokens."""
        self._tokens = {
            t: e for t, e in self._tokens.items()
            if not e.consumed and e.is_valid()
        }

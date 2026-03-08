"""Persistent storage for Feishu User Access Tokens (UAT).

Stores tokens as JSON files with restricted permissions.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

REFRESH_AHEAD_MS = 5 * 60 * 1000  # 5 minutes


@dataclass
class StoredToken:
    app_id: str
    user_open_id: str
    access_token: str
    refresh_token: str
    expires_at: int          # ms epoch
    refresh_expires_at: int  # ms epoch
    scope: str
    granted_at: int          # ms epoch


def token_status(token: StoredToken) -> str:
    """Check token freshness: 'valid', 'needs_refresh', or 'expired'."""
    now = int(time.time() * 1000)
    if now < token.expires_at - REFRESH_AHEAD_MS:
        return "valid"
    if now < token.refresh_expires_at:
        return "needs_refresh"
    return "expired"


def _safe_filename(app_id: str, user_open_id: str) -> str:
    key = f"{app_id}_{user_open_id}"
    return re.sub(r"[^a-zA-Z0-9._-]", "_", key) + ".json"


class FileTokenStore:
    """File-based token store. Tokens stored as JSON in a restricted directory."""

    def __init__(self, base_dir: Path) -> None:
        self._dir = Path(base_dir)

    async def get(self, app_id: str, user_open_id: str) -> StoredToken | None:
        path = self._dir / _safe_filename(app_id, user_open_id)
        try:
            data = json.loads(path.read_text())
            return StoredToken(**data)
        except (FileNotFoundError, json.JSONDecodeError, TypeError):
            return None

    async def set(self, token: StoredToken) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._dir / _safe_filename(token.app_id, token.user_open_id)
        path.write_text(json.dumps(asdict(token)))
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        logger.info("token-store: saved UAT for %s", token.user_open_id)

    async def remove(self, app_id: str, user_open_id: str) -> None:
        path = self._dir / _safe_filename(app_id, user_open_id)
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        logger.info("token-store: removed UAT for %s", user_open_id)

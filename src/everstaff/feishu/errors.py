"""Canonical Feishu auth error classes."""
from __future__ import annotations


class UserAuthRequiredError(Exception):
    """Raised when a Feishu tool call requires user authorization."""

    def __init__(self, user_open_id: str, required_scopes: list[str] | None = None, app_id: str = "") -> None:
        self.user_open_id = user_open_id
        self.required_scopes = required_scopes or []
        self.app_id = app_id
        super().__init__(f"User {user_open_id} needs authorization for scopes: {self.required_scopes}")

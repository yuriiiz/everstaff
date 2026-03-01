"""API authentication package.

Exports the core types and middleware used by the rest of the application.
"""

from __future__ import annotations

from everstaff.api.auth.middleware import (
    AuthMiddleware,
    authenticate_token,
    get_current_user,
)
from everstaff.api.auth.models import AuthConfig, UserIdentity
from everstaff.api.auth.providers import AuthProvider

__all__ = [
    "AuthConfig",
    "AuthMiddleware",
    "AuthProvider",
    "UserIdentity",
    "authenticate_token",
    "get_current_user",
]

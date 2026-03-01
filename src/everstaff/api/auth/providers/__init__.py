"""Auth providers — abstract base class for authentication providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from starlette.requests import Request

from everstaff.api.auth.models import UserIdentity


class AuthProvider(ABC):
    """Base class for all authentication providers.

    Each provider inspects the incoming request and returns a ``UserIdentity``
    if it can authenticate the caller, or ``None`` if the request does not
    contain credentials relevant to this provider.
    """

    @abstractmethod
    async def authenticate(self, request: Request) -> UserIdentity | None:
        """Return UserIdentity on success, None if this provider doesn't apply."""
        ...

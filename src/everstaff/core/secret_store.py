"""In-memory secret storage — never leaks to os.environ or disk."""
from __future__ import annotations

import os


class SecretStore:
    """Hold secrets in Python memory only.

    Unlike os.environ, values stored here are not inherited by
    subprocesses and not visible via ``printenv`` or ``/proc/*/environ``.
    """

    def __init__(self, secrets: dict[str, str] | None = None) -> None:
        self._data: dict[str, str] = dict(secrets) if secrets else {}

    @classmethod
    def from_environ(cls) -> SecretStore:
        """Snapshot current os.environ into a SecretStore."""
        return cls(dict(os.environ))

    def get(self, key: str, default: str | None = None) -> str | None:
        return self._data.get(key, default)

    def as_dict(self) -> dict[str, str]:
        """Return a copy of all secrets."""
        return dict(self._data)

    def subset(self, keys: list[str]) -> dict[str, str]:
        """Return dict containing only the requested keys (missing keys skipped)."""
        return {k: self._data[k] for k in keys if k in self._data}

    def __contains__(self, key: str) -> bool:
        return key in self._data

    def __len__(self) -> int:
        return len(self._data)

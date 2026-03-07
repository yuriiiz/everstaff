"""Shared fixtures for daemon tests."""
import pytest

from everstaff.daemon.state_store import DaemonStateStore


class InMemoryFileStore:
    """Minimal FileStore implementation for testing."""

    def __init__(self):
        self._data: dict[str, bytes] = {}

    async def read(self, path: str) -> bytes:
        if path not in self._data:
            raise FileNotFoundError(path)
        return self._data[path]

    async def write(self, path: str, data: bytes) -> None:
        self._data[path] = data

    async def exists(self, path: str) -> bool:
        return path in self._data

    async def delete(self, path: str) -> None:
        self._data.pop(path, None)

    async def list(self, prefix: str) -> list[str]:
        return [k for k in self._data if k.startswith(prefix)]


class FakeMem0:
    """Minimal Mem0Client stand-in for testing."""

    def __init__(self):
        self.added: list[tuple] = []
        self.searched: list[str] = []

    async def add(self, messages, **scope):
        self.added.append((messages, scope))
        return []

    async def search(self, query, *, top_k=None, **scope):
        self.searched.append(query)
        return [{"memory": "relevant context", "score": 0.9}]


@pytest.fixture
def file_store():
    return InMemoryFileStore()


@pytest.fixture
def state_store():
    return DaemonStateStore(InMemoryFileStore())


@pytest.fixture
def fake_mem0():
    return FakeMem0()

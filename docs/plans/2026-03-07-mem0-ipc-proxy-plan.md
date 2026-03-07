# Mem0 IPC Proxy Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Proxy mem0 `add`/`search` operations over IPC to the orchestrator so sandbox processes don't run mem0 locally (fixing faiss path and concurrency issues).

**Architecture:** Create `ProxyMem0Client` in sandbox (same interface as `Mem0Client`) that forwards calls over IPC. Add `mem0.add`/`mem0.search` handlers to `IpcServerHandler`. Wire orchestrator's `Mem0Client` into the handler. Clean up sandbox's direct mem0 usage.

**Tech Stack:** Existing IPC infrastructure (JSON-RPC 2.0 over Unix socket), `Mem0Client`, `IpcServerHandler`

---

### Task 1: Create ProxyMem0Client

**Files:**
- Create: `src/everstaff/sandbox/proxy/mem0_client.py`
- Test: `tests/test_sandbox/test_proxy_mem0_client.py`

**Step 1: Write the failing test**

```python
"""Tests for ProxyMem0Client."""
import pytest
from unittest.mock import AsyncMock, MagicMock


class TestProxyMem0ClientSearch:
    @pytest.mark.asyncio
    async def test_search_forwards_over_ipc(self):
        from everstaff.sandbox.proxy.mem0_client import ProxyMem0Client
        channel = MagicMock()
        channel.send_request = AsyncMock(return_value=[
            {"memory": "likes python", "score": 0.9},
        ])
        client = ProxyMem0Client(channel)
        results = await client.search("what do they like", user_id="u1", agent_id="a1")
        channel.send_request.assert_called_once_with("mem0.search", {
            "query": "what do they like",
            "top_k": None,
            "user_id": "u1",
            "agent_id": "a1",
        })
        assert results == [{"memory": "likes python", "score": 0.9}]

    @pytest.mark.asyncio
    async def test_search_with_top_k(self):
        from everstaff.sandbox.proxy.mem0_client import ProxyMem0Client
        channel = MagicMock()
        channel.send_request = AsyncMock(return_value=[])
        client = ProxyMem0Client(channel)
        await client.search("q", top_k=5, user_id="u1")
        call_params = channel.send_request.call_args[0][1]
        assert call_params["top_k"] == 5


class TestProxyMem0ClientAdd:
    @pytest.mark.asyncio
    async def test_add_forwards_over_ipc(self):
        from everstaff.sandbox.proxy.mem0_client import ProxyMem0Client
        channel = MagicMock()
        channel.send_request = AsyncMock(return_value={"results": []})
        client = ProxyMem0Client(channel)
        messages = [{"role": "user", "content": "I like Python"}]
        result = await client.add(messages, user_id="u1", agent_id="a1", run_id="s1")
        channel.send_request.assert_called_once_with("mem0.add", {
            "messages": messages,
            "user_id": "u1",
            "agent_id": "a1",
            "run_id": "s1",
        })
        assert result == {"results": []}
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_sandbox/test_proxy_mem0_client.py -v`
Expected: FAIL (module not found)

**Step 3: Write implementation**

```python
"""ProxyMem0Client — forwards mem0 operations over IPC to orchestrator."""
from __future__ import annotations

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from everstaff.sandbox.ipc.channel import IpcChannel


class ProxyMem0Client:
    """Mem0Client replacement that proxies add/search over IPC."""

    def __init__(self, channel: "IpcChannel") -> None:
        self._channel = channel

    async def add(self, messages: list[dict], **scope: Any) -> Any:
        params: dict[str, Any] = {"messages": messages}
        params.update(scope)
        return await self._channel.send_request("mem0.add", params)

    async def search(self, query: str, *, top_k: int | None = None, **scope: Any) -> list[dict]:
        params: dict[str, Any] = {"query": query, "top_k": top_k}
        params.update(scope)
        return await self._channel.send_request("mem0.search", params)
```

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_sandbox/test_proxy_mem0_client.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/everstaff/sandbox/proxy/mem0_client.py tests/test_sandbox/test_proxy_mem0_client.py
git commit -m "feat(sandbox): add ProxyMem0Client for IPC-based mem0"
```

---

### Task 2: Add mem0 handlers to IpcServerHandler

**Files:**
- Modify: `src/everstaff/sandbox/ipc/server_handler.py`
- Test: `tests/test_sandbox/test_ipc_mem0_handler.py`

**Step 1: Write the failing test**

```python
"""Tests for IPC mem0 handler routes."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mem0_client():
    client = MagicMock()
    client.add = AsyncMock(return_value={"results": [{"id": "m1", "event": "ADD"}]})
    client.search = AsyncMock(return_value=[{"memory": "likes python", "score": 0.9}])
    return client


@pytest.fixture
def handler(mem0_client):
    from everstaff.sandbox.ipc.server_handler import IpcServerHandler
    from everstaff.sandbox.token_store import EphemeralTokenStore
    from everstaff.core.secret_store import SecretStore
    h = IpcServerHandler(
        token_store=EphemeralTokenStore(),
        secret_store=SecretStore({}),
    )
    h._mem0_client = mem0_client
    return h


class TestMem0Add:
    @pytest.mark.asyncio
    async def test_routes_to_mem0_add(self, handler, mem0_client):
        result = await handler.handle("mem0.add", {
            "messages": [{"role": "user", "content": "I like Python"}],
            "user_id": "u1",
            "agent_id": "a1",
            "run_id": "s1",
        })
        mem0_client.add.assert_called_once_with(
            [{"role": "user", "content": "I like Python"}],
            user_id="u1", agent_id="a1", run_id="s1",
        )
        assert result == {"results": [{"id": "m1", "event": "ADD"}]}


class TestMem0Search:
    @pytest.mark.asyncio
    async def test_routes_to_mem0_search(self, handler, mem0_client):
        result = await handler.handle("mem0.search", {
            "query": "what do they like",
            "top_k": 5,
            "user_id": "u1",
        })
        mem0_client.search.assert_called_once_with(
            "what do they like", top_k=5, user_id="u1",
        )
        assert result == [{"memory": "likes python", "score": 0.9}]

    @pytest.mark.asyncio
    async def test_search_without_mem0_returns_empty(self):
        from everstaff.sandbox.ipc.server_handler import IpcServerHandler
        from everstaff.sandbox.token_store import EphemeralTokenStore
        from everstaff.core.secret_store import SecretStore
        h = IpcServerHandler(
            token_store=EphemeralTokenStore(),
            secret_store=SecretStore({}),
        )
        # No mem0_client set
        result = await h.handle("mem0.search", {"query": "test", "user_id": "u1"})
        assert result == []
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_sandbox/test_ipc_mem0_handler.py -v`
Expected: FAIL (mem0 routes not implemented)

**Step 3: Modify IpcServerHandler**

In `src/everstaff/sandbox/ipc/server_handler.py`:

Add `mem0_client` parameter to `__init__`:

```python
    def __init__(
        self,
        memory_store: "MemoryStore | None" = None,
        tracer: "TracingBackend | None" = None,
        file_store: "FileStore | None" = None,
        token_store: "EphemeralTokenStore | None" = None,
        secret_store: "SecretStore | None" = None,
        on_hitl_detected: Callable[..., Awaitable[None]] | None = None,
        on_stream_event: Callable[[dict], Awaitable[None]] | None = None,
        config_data: dict[str, Any] | None = None,
        mem0_client: Any | None = None,
    ) -> None:
        # ... existing assignments ...
        self._mem0_client = mem0_client
```

Add routing in `handle()` method, BEFORE the `method.startswith("memory.")` check:

```python
            elif method.startswith("mem0."):
                return await self._handle_mem0(method, params)
```

Add handler method:

```python
    async def _handle_mem0(self, method: str, params: dict[str, Any]) -> Any:
        """Handle mem0.add / mem0.search."""
        op = method.split(".", 1)[1]
        if self._mem0_client is None:
            if op == "search":
                return []
            return {"results": []}
        if op == "add":
            messages = params.pop("messages", [])
            scope = {k: v for k, v in params.items() if v is not None}
            return await self._mem0_client.add(messages, **scope)
        elif op == "search":
            query = params.pop("query", "")
            top_k = params.pop("top_k", None)
            scope = {k: v for k, v in params.items() if v is not None}
            return await self._mem0_client.search(query, top_k=top_k, **scope)
        return {"error": f"Unknown mem0 operation: {op}"}
```

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_sandbox/test_ipc_mem0_handler.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/everstaff/sandbox/ipc/server_handler.py tests/test_sandbox/test_ipc_mem0_handler.py
git commit -m "feat(sandbox): add mem0.add/search IPC handler routes"
```

---

### Task 3: Wire Mem0Client into orchestrator IPC

**Files:**
- Modify: `src/everstaff/sandbox/mixin.py:144-149`

**Step 1: Update `_start_ipc` to pass mem0_client**

Add `mem0_client` parameter to `configure_ipc` and pass it through:

In `configure_ipc()`, add parameter and store it:

```python
    def configure_ipc(
        self,
        secret_store: "SecretStore | None" = None,
        memory_store: "MemoryStore | None" = None,
        tracer: "TracingBackend | None" = None,
        file_store: "FileStore | None" = None,
        config_data: dict[str, Any] | None = None,
        on_stream_event: Callable[..., Awaitable[None]] | None = None,
        on_hitl_detected: Callable[..., Awaitable[None]] | None = None,
        mem0_client: Any | None = None,
    ) -> None:
        # ... existing assignments ...
        self._mem0_client = mem0_client
```

In `_start_ipc()`, pass it to handler:

```python
        self._ipc_handler = IpcServerHandler(
            memory_store=self._memory_store, tracer=self._tracer, file_store=self._file_store,
            token_store=self._token_store, secret_store=self._secret_store,
            on_stream_event=self._on_stream_event, on_hitl_detected=self._on_hitl_detected,
            config_data=self._config_data,
            mem0_client=self._mem0_client,
        )
```

**Step 2: Find where `configure_ipc` is called and pass mem0_client**

Search for `configure_ipc(` calls. The caller (likely `ExecutorManager` or similar) needs to create a `Mem0Client` from `DefaultEnvironment` and pass it.

Find the caller file and add:

```python
# Where configure_ipc is called, add mem0_client:
mem0_client = env._get_or_create_mem0_client() if env._config and env._config.memory.enabled else None
sandbox.configure_ipc(
    ...,
    mem0_client=mem0_client,
)
```

**Step 3: Run existing sandbox tests**

Run: `python3 -m pytest tests/test_sandbox/ -v`
Expected: PASS

**Step 4: Commit**

```bash
git add src/everstaff/sandbox/mixin.py <caller-file>
git commit -m "feat(sandbox): wire Mem0Client into IPC handler"
```

---

### Task 4: Update SandboxEnvironment to use ProxyMem0Client

**Files:**
- Modify: `src/everstaff/sandbox/environment.py`
- Test: `tests/test_sandbox/test_sandbox_environment.py` (or existing wiring tests)

**Step 1: Rewrite SandboxEnvironment mem0 methods**

Replace the entire mem0 section (lines 59-86) with:

```python
    # --- mem0 integration (proxied to orchestrator via IPC) ---

    def _get_or_create_mem0_client(self):
        if not hasattr(self, "_mem0_client"):
            from everstaff.sandbox.proxy.mem0_client import ProxyMem0Client
            self._mem0_client = ProxyMem0Client(self._channel)
        return self._mem0_client

    def build_mem0_provider(self, **mem0_scope):
        if not self._config.memory.enabled:
            return None
        from everstaff.memory.mem0_provider import Mem0Provider
        return Mem0Provider(self._get_or_create_mem0_client(), **mem0_scope)

    def build_mem0_hook(self, provider, memory_store, **mem0_scope):
        if not self._config.memory.enabled:
            return None
        from everstaff.memory.mem0_hook import Mem0Hook
        return Mem0Hook(
            mem0_provider=provider,
            mem0_client=self._get_or_create_mem0_client(),
            memory_store=memory_store,
            **mem0_scope,
        )
```

Remove `_EMBEDDER_API_KEY_MAP` dict from module level.

Remove the `from everstaff.memory.mem0_client import Mem0Client` import that was in the old `_get_or_create_mem0_client`.

**Step 2: Run all tests**

Run: `python3 -m pytest tests/test_sandbox/ tests/test_memory/ -v`
Expected: PASS

**Step 3: Commit**

```bash
git add src/everstaff/sandbox/environment.py
git commit -m "feat(sandbox): use ProxyMem0Client instead of direct mem0"
```

---

### Task 5: Clean up — remove sandbox secret bridge install (optional)

**Files:**
- Modify: `src/everstaff/sandbox/entry.py:54-57`

**Step 1: Evaluate**

The `install_secret_bridge` call in `entry.py` is still useful if sandbox makes direct litellm LLM calls (e.g. via `LiteLLMClient` for agent chat). Keep it if sandbox runs LLM calls directly. Only remove if ALL LLM calls are proxied.

Since `build_llm_client` in `SandboxEnvironment` returns `LiteLLMClient` (direct), **keep the secret bridge**. No changes needed.

**Step 2: Run full test suite**

Run: `python3 -m pytest tests/test_memory/ tests/test_llm/ tests/test_sandbox/ -v`
Expected: PASS

**Step 3: Commit if any fixups needed**

```bash
git add -u
git commit -m "test: verify mem0 IPC proxy end-to-end"
```

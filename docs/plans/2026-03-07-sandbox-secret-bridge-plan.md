# Sandbox Secret Bridge Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Bridge `SecretStore` to litellm's `CustomSecretManager` so sandbox subprocesses can access API keys without leaking them to `os.environ`.

**Architecture:** Implement a `SecretStoreBridge` (litellm `CustomSecretManager` subclass) that reads from `SecretStore`. Install it in sandbox `entry.py` after IPC auth. Pass embedder `api_key` explicitly to `Mem0Client` since mem0's embedder bypasses litellm.

**Tech Stack:** litellm `CustomSecretManager`, existing `SecretStore`

---

### Task 1: Create SecretStoreBridge

**Files:**
- Create: `src/everstaff/llm/secret_bridge.py`
- Test: `tests/test_llm/test_secret_bridge.py`

**Step 1: Write the failing test**

```python
"""Tests for SecretStoreBridge."""
import pytest
from everstaff.core.secret_store import SecretStore


class TestSecretStoreBridge:
    def test_sync_read_existing_key(self):
        from everstaff.llm.secret_bridge import SecretStoreBridge
        store = SecretStore({"OPENAI_API_KEY": "sk-test-123"})
        bridge = SecretStoreBridge(store)
        assert bridge.sync_read_secret("OPENAI_API_KEY") == "sk-test-123"

    def test_sync_read_missing_key(self):
        from everstaff.llm.secret_bridge import SecretStoreBridge
        store = SecretStore({})
        bridge = SecretStoreBridge(store)
        assert bridge.sync_read_secret("MISSING_KEY") is None

    @pytest.mark.asyncio
    async def test_async_read_existing_key(self):
        from everstaff.llm.secret_bridge import SecretStoreBridge
        store = SecretStore({"API_KEY": "val"})
        bridge = SecretStoreBridge(store)
        assert await bridge.async_read_secret("API_KEY") == "val"


class TestInstallSecretBridge:
    def test_install_configures_litellm(self):
        import litellm
        from everstaff.llm.secret_bridge import SecretStoreBridge, install_secret_bridge
        store = SecretStore({"KEY": "val"})
        install_secret_bridge(store)
        assert isinstance(litellm.secret_manager_client, SecretStoreBridge)
        assert litellm._key_management_system is not None
        assert litellm._key_management_settings is not None
        # Cleanup
        litellm.secret_manager_client = None
        litellm._key_management_system = None
        litellm._key_management_settings = None
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_llm/test_secret_bridge.py -v`
Expected: FAIL (module not found)

**Step 3: Write implementation**

```python
"""Bridge SecretStore to litellm's secret manager interface."""
from __future__ import annotations

from typing import Optional, Union, TYPE_CHECKING

import httpx
import litellm
from litellm.integrations.custom_secret_manager import CustomSecretManager
from litellm.types.secret_managers.main import KeyManagementSystem, KeyManagementSettings

if TYPE_CHECKING:
    from everstaff.core.secret_store import SecretStore


class SecretStoreBridge(CustomSecretManager):
    """litellm CustomSecretManager backed by everstaff SecretStore."""

    def __init__(self, secret_store: "SecretStore") -> None:
        super().__init__(secret_manager_name="everstaff")
        self._store = secret_store

    async def async_read_secret(
        self,
        secret_name: str,
        optional_params: Optional[dict] = None,
        timeout: Optional[Union[float, httpx.Timeout]] = None,
    ) -> Optional[str]:
        return self._store.get(secret_name)

    def sync_read_secret(
        self,
        secret_name: str,
        optional_params: Optional[dict] = None,
        timeout: Optional[Union[float, httpx.Timeout]] = None,
    ) -> Optional[str]:
        return self._store.get(secret_name)


def install_secret_bridge(secret_store: "SecretStore") -> None:
    """Register SecretStore as litellm's secret provider."""
    litellm.secret_manager_client = SecretStoreBridge(secret_store)
    litellm._key_management_system = KeyManagementSystem.CUSTOM
    litellm._key_management_settings = KeyManagementSettings(access_mode="read_only")
```

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_llm/test_secret_bridge.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/everstaff/llm/secret_bridge.py tests/test_llm/test_secret_bridge.py
git commit -m "feat(sandbox): add SecretStoreBridge for litellm"
```

---

### Task 2: Install bridge in sandbox entry.py

**Files:**
- Modify: `src/everstaff/sandbox/entry.py:52-58`

**Step 1: Add install call after IPC auth**

In `sandbox_main()`, after `secret_store = SecretStore(...)` and before building `SandboxEnvironment`, add:

```python
        secret_store = SecretStore(auth_result.get("secrets", {}))

        # Bridge SecretStore to litellm so LLM calls can find API keys
        # without leaking them to os.environ.
        from everstaff.llm.secret_bridge import install_secret_bridge
        install_secret_bridge(secret_store)

        # Parse config from orchestrator
```

**Step 2: Verify existing tests still pass**

Run: `python3 -m pytest tests/test_memory/ tests/test_llm/ -v`
Expected: All pass

**Step 3: Commit**

```bash
git add src/everstaff/sandbox/entry.py
git commit -m "feat(sandbox): install secret bridge in sandbox entry"
```

---

### Task 3: Pass embedder api_key to Mem0Client

**Files:**
- Modify: `src/everstaff/memory/mem0_client.py:25-50`
- Modify: `src/everstaff/sandbox/environment.py:61-68`
- Modify: `src/everstaff/builder/environment.py:128-135`
- Test: `tests/test_memory/test_mem0_client.py`

**Step 1: Update test to verify api_key passthrough**

Add test in `tests/test_memory/test_mem0_client.py`:

```python
class TestMem0ClientEmbedderApiKey:
    def test_api_key_passed_to_embedder_config(self):
        with patch("everstaff.memory.mem0_client.Memory") as MockMemory:
            MockMemory.from_config.return_value = MagicMock()
            from everstaff.memory.mem0_client import Mem0Client
            config = MemoryConfig(enabled=True)
            Mem0Client(config, "openai/gpt-4.1-nano", "text-embedding-3-small",
                       embedder_api_key="sk-test")
            call_args = MockMemory.from_config.call_args[0][0]
            assert call_args["embedder"]["config"]["api_key"] == "sk-test"

    def test_no_api_key_omits_field(self):
        with patch("everstaff.memory.mem0_client.Memory") as MockMemory:
            MockMemory.from_config.return_value = MagicMock()
            from everstaff.memory.mem0_client import Mem0Client
            config = MemoryConfig(enabled=True)
            Mem0Client(config, "openai/gpt-4.1-nano", "text-embedding-3-small")
            call_args = MockMemory.from_config.call_args[0][0]
            assert "api_key" not in call_args["embedder"]["config"]
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_memory/test_mem0_client.py::TestMem0ClientEmbedderApiKey -v`
Expected: FAIL

**Step 3: Update Mem0Client to accept embedder_api_key**

In `mem0_client.py`, change `__init__`:

```python
    def __init__(
        self,
        config: "MemoryConfig",
        llm_model_id: str,
        embedding_model_id: str,
        embedder_api_key: str | None = None,
    ) -> None:
        if Memory is None:
            raise ImportError(
                "mem0ai is required for memory integration. "
                "Install it with: pip install 'everstaff[mem0]'"
            )
        embed_provider, embed_model = self._parse_embedding_model(embedding_model_id)
        embedder_config: dict = {"model": embed_model}
        if embedder_api_key:
            embedder_config["api_key"] = embedder_api_key
        self._memory = Memory.from_config({
            "llm": {
                "provider": "litellm",
                "config": {"model": llm_model_id},
            },
            "embedder": {
                "provider": embed_provider,
                "config": embedder_config,
            },
            "vector_store": {
                "provider": config.vector_store,
                "config": {"path": config.vector_store_path},
            },
        })
        self._top_k = config.search_top_k
        self._threshold = config.search_threshold
```

**Step 4: Update environment layers to pass api_key from SecretStore**

The embedder provider name maps to an API key env var. For simplicity, use a
mapping for known providers. The key env var names follow litellm/mem0 conventions.

In `sandbox/environment.py`, update `_get_or_create_mem0_client`:

```python
    def _get_or_create_mem0_client(self):
        if not hasattr(self, "_mem0_client"):
            from everstaff.memory.mem0_client import Mem0Client
            mem = self._config.memory
            llm_model_id = self._config.resolve_model(mem.llm_model_kind).model_id
            embed_model_id = self._config.resolve_model(mem.embedding_model_kind).model_id
            embed_provider, _ = Mem0Client._parse_embedding_model(embed_model_id)
            embedder_api_key = self._secret_store.get(
                _EMBEDDER_API_KEY_MAP.get(embed_provider, f"{embed_provider.upper()}_API_KEY")
            )
            self._mem0_client = Mem0Client(mem, llm_model_id, embed_model_id,
                                           embedder_api_key=embedder_api_key)
        return self._mem0_client
```

Add at module level in `sandbox/environment.py`:

```python
_EMBEDDER_API_KEY_MAP = {
    "openai": "OPENAI_API_KEY",
    "azure_openai": "AZURE_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "together": "TOGETHER_API_KEY",
}
```

In `builder/environment.py` (DefaultEnvironment), no change needed — `os.environ`
is available, so `embedder_api_key=None` is fine (mem0 reads from env).

**Step 5: Run all memory tests**

Run: `python3 -m pytest tests/test_memory/ -v`
Expected: All pass

**Step 6: Commit**

```bash
git add src/everstaff/memory/mem0_client.py src/everstaff/sandbox/environment.py tests/test_memory/test_mem0_client.py
git commit -m "feat(mem0): pass embedder api_key from SecretStore"
```

---

### Task 4: Update wiring test for sandbox environment

**Files:**
- Test: `tests/test_memory/test_mem0_wiring.py`

**Step 1: Verify all tests pass end-to-end**

Run: `python3 -m pytest tests/test_memory/ tests/test_llm/ -v`
Expected: All pass (wiring tests use mock Memory, so api_key=None is fine)

**Step 2: Final commit if any fixups needed**

```bash
git add -u
git commit -m "test: fixup sandbox secret bridge tests"
```

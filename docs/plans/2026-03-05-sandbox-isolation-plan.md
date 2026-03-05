# Sandbox Isolation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Isolate agent session execution from the main service process so that secrets cannot leak via environment variables, even if an agent is compromised by prompt injection.

**Architecture:** Orchestrator + Sandbox Session. The Orchestrator (main process) holds all secrets and manages lifecycle/HITL/scheduling. Each session's AgentRuntime runs inside an isolated Sandbox Executor with secrets stored only in Python memory (SecretStore), never in `os.environ` or on disk. Bash subprocesses get a clean (empty) environment.

**Tech Stack:** Python 3.11+, asyncio, Pydantic, Unix sockets, TLS (ssl module), Docker SDK (optional)

**Design doc:** `docs/plans/2026-03-05-sandbox-isolation-design.md`

---

## Phase 1: SecretStore + Environment Filtering (Foundation)

This phase delivers immediate value: Bash subprocesses no longer inherit `os.environ`.

### Task 1: SecretStore — In-Memory Secret Storage

**Files:**
- Create: `src/everstaff/core/secret_store.py`
- Test: `tests/test_core/test_secret_store.py`

**Step 1: Write the failing test**

```python
# tests/test_core/test_secret_store.py
"""Tests for the in-memory SecretStore."""
import os
import pytest
from everstaff.core.secret_store import SecretStore


class TestSecretStore:
    def test_create_empty(self):
        store = SecretStore()
        assert store.get("ANY_KEY") is None
        assert store.as_dict() == {}

    def test_create_from_dict(self):
        store = SecretStore({"API_KEY": "sk-123", "DB_PASS": "secret"})
        assert store.get("API_KEY") == "sk-123"
        assert store.get("DB_PASS") == "secret"
        assert store.get("MISSING") is None

    def test_as_dict_returns_copy(self):
        store = SecretStore({"KEY": "val"})
        d = store.as_dict()
        d["KEY"] = "tampered"
        assert store.get("KEY") == "val"  # original unmodified

    def test_subset_returns_filtered_dict(self):
        store = SecretStore({"A": "1", "B": "2", "C": "3"})
        sub = store.subset(["A", "C"])
        assert sub == {"A": "1", "C": "3"}

    def test_subset_ignores_missing_keys(self):
        store = SecretStore({"A": "1"})
        sub = store.subset(["A", "MISSING"])
        assert sub == {"A": "1"}

    def test_from_environ_captures_snapshot(self):
        os.environ["_TEST_SECRET_STORE"] = "test_val"
        try:
            store = SecretStore.from_environ()
            assert store.get("_TEST_SECRET_STORE") == "test_val"
            # Changing os.environ after creation does not affect store
            os.environ["_TEST_SECRET_STORE"] = "changed"
            assert store.get("_TEST_SECRET_STORE") == "test_val"
        finally:
            os.environ.pop("_TEST_SECRET_STORE", None)

    def test_not_in_os_environ(self):
        """SecretStore does NOT leak into os.environ."""
        store = SecretStore({"PRIVATE": "secret"})
        assert os.environ.get("PRIVATE") is None

    def test_len(self):
        store = SecretStore({"A": "1", "B": "2"})
        assert len(store) == 2

    def test_contains(self):
        store = SecretStore({"A": "1"})
        assert "A" in store
        assert "B" not in store
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_core/test_secret_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'everstaff.core.secret_store'`

**Step 3: Write minimal implementation**

```python
# src/everstaff/core/secret_store.py
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
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_core/test_secret_store.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/everstaff/core/secret_store.py tests/test_core/test_secret_store.py
git commit -m "feat: add SecretStore for in-memory secret storage"
```

---

### Task 2: SandboxConfig — Configuration Model

**Files:**
- Modify: `src/everstaff/core/config.py` (add SandboxConfig to FrameworkConfig)
- Test: `tests/test_core/test_config.py` (add sandbox config tests)

**Step 1: Write the failing test**

```python
# Add to tests/test_core/test_config.py (or create if not exists)
import pytest
from everstaff.core.config import FrameworkConfig, SandboxConfig


class TestSandboxConfig:
    def test_default_sandbox_config(self):
        cfg = FrameworkConfig()
        assert cfg.sandbox is not None
        assert cfg.sandbox.enabled is False
        assert cfg.sandbox.type == "auto"
        assert cfg.sandbox.idle_timeout == 300
        assert cfg.sandbox.token_ttl == 30

    def test_sandbox_config_from_dict(self):
        cfg = FrameworkConfig(sandbox={"enabled": True, "type": "docker", "idle_timeout": 600})
        assert cfg.sandbox.enabled is True
        assert cfg.sandbox.type == "docker"
        assert cfg.sandbox.idle_timeout == 600

    def test_sandbox_docker_config(self):
        cfg = FrameworkConfig(sandbox={
            "enabled": True,
            "type": "docker",
            "docker": {"image": "custom:latest", "memory_limit": "1g"},
        })
        assert cfg.sandbox.docker.image == "custom:latest"
        assert cfg.sandbox.docker.memory_limit == "1g"

    def test_sandbox_extra_mounts(self):
        cfg = FrameworkConfig(sandbox={
            "enabled": True,
            "extra_mounts": [
                {"source": "/data/models", "target": "/mnt/models", "readonly": True}
            ],
        })
        assert len(cfg.sandbox.extra_mounts) == 1
        assert cfg.sandbox.extra_mounts[0].source == "/data/models"
        assert cfg.sandbox.extra_mounts[0].readonly is True
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_core/test_config.py::TestSandboxConfig -v`
Expected: FAIL — `ImportError: cannot import name 'SandboxConfig'`

**Step 3: Write minimal implementation**

Add to `src/everstaff/core/config.py` before the `FrameworkConfig` class:

```python
class SandboxMountConfig(BaseModel):
    source: str
    target: str
    readonly: bool = True


class SandboxDockerConfig(BaseModel):
    image: str = "everstaff/executor:latest"
    memory_limit: str = "512m"
    cpu_limit: float = 1.0


class SandboxConfig(BaseModel):
    enabled: bool = False
    type: Literal["auto", "process", "docker"] = "auto"
    idle_timeout: int = 300  # seconds
    token_ttl: int = 30  # ephemeral token validity in seconds
    docker: SandboxDockerConfig = Field(default_factory=SandboxDockerConfig)
    extra_mounts: list[SandboxMountConfig] = Field(default_factory=list)
```

Add field to `FrameworkConfig`:

```python
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_core/test_config.py::TestSandboxConfig -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/everstaff/core/config.py tests/test_core/test_config.py
git commit -m "feat: add SandboxConfig to FrameworkConfig"
```

---

### Task 3: Bash Tool — Clean Environment

This is the **highest-value change**: Bash subprocesses no longer inherit parent env.

**Files:**
- Modify: `src/everstaff/builtin_tools/bash.py` (add env parameter)
- Test: `tests/test_builtin_tools/test_bash_env.py`

**Step 1: Write the failing test**

```python
# tests/test_builtin_tools/test_bash_env.py
"""Tests for Bash tool environment isolation."""
import os
import pytest
from pathlib import Path
from everstaff.builtin_tools.bash import make_bash_tool


@pytest.mark.asyncio
class TestBashEnvironmentIsolation:
    async def test_bash_default_clean_env(self, tmp_path):
        """Bash subprocess should NOT inherit parent os.environ by default."""
        os.environ["_TEST_SECRET_KEY"] = "super_secret_value"
        try:
            bash = make_bash_tool(tmp_path)
            result = await bash.execute({"command": "echo $_TEST_SECRET_KEY"})
            # Should be empty — clean env does not have _TEST_SECRET_KEY
            assert "super_secret_value" not in result
        finally:
            os.environ.pop("_TEST_SECRET_KEY", None)

    async def test_bash_has_minimal_env(self, tmp_path):
        """Bash subprocess should have PATH so basic commands work."""
        bash = make_bash_tool(tmp_path)
        result = await bash.execute({"command": "echo hello"})
        assert "hello" in result

    async def test_bash_printenv_is_minimal(self, tmp_path):
        """printenv should return very few variables."""
        bash = make_bash_tool(tmp_path)
        result = await bash.execute({"command": "env | wc -l"})
        # Clean env should have very few vars (PATH, HOME, maybe a few more)
        line_count = int(result.strip().split("\n")[0])
        assert line_count < 10  # Parent env typically has 30+

    async def test_bash_with_custom_env(self, tmp_path):
        """make_bash_tool should accept extra env vars."""
        extra_env = {"CUSTOM_VAR": "custom_value"}
        bash = make_bash_tool(tmp_path, env=extra_env)
        result = await bash.execute({"command": "echo $CUSTOM_VAR"})
        assert "custom_value" in result

    async def test_bash_custom_env_does_not_leak_parent(self, tmp_path):
        """Custom env should not include parent os.environ."""
        os.environ["_TEST_LEAK_CHECK"] = "should_not_appear"
        try:
            bash = make_bash_tool(tmp_path, env={"SAFE": "yes"})
            result = await bash.execute({"command": "echo $_TEST_LEAK_CHECK"})
            assert "should_not_appear" not in result
        finally:
            os.environ.pop("_TEST_LEAK_CHECK", None)
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_builtin_tools/test_bash_env.py -v`
Expected: FAIL — `make_bash_tool() got an unexpected keyword argument 'env'` and env leakage assertions fail

**Step 3: Modify bash.py**

Modify `src/everstaff/builtin_tools/bash.py`:

```python
"""Bash — execute shell commands within the agent's workspace."""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from everstaff.tools.native import tool

logger = logging.getLogger(__name__)


def _minimal_env() -> dict[str, str]:
    """Build a minimal environment for subprocess execution.

    Only includes PATH and HOME so basic commands work.
    Does NOT inherit parent process secrets.
    """
    env: dict[str, str] = {}
    for key in ("PATH", "HOME", "USER", "LANG", "TERM"):
        val = os.environ.get(key)
        if val is not None:
            env[key] = val
    return env


def _bash_permission_hint(args):
    from everstaff.protocols import PermissionHint
    cmd = args.get("command", "").strip()
    if not cmd:
        return PermissionHint("command", "*")
    prefix = cmd.split()[0]
    return PermissionHint("command", f"{prefix} *")


def make_bash_tool(workdir: Path, env: dict[str, str] | None = None):
    """Return a Bash NativeTool scoped to *workdir*.

    Parameters
    ----------
    workdir:
        Working directory for command execution.
    env:
        Extra environment variables to inject into the subprocess.
        These are merged on top of a minimal base env (PATH, HOME, etc.).
        Parent ``os.environ`` is **never** inherited.
    """
    # Build subprocess environment: minimal base + caller extras
    subprocess_env = _minimal_env()
    if env:
        subprocess_env.update(env)

    @tool(name="Bash", description="Execute a shell command and return stdout + stderr.",
          permission_hint=_bash_permission_hint)
    async def bash(command: str, timeout: int = 300) -> str:
        """Execute a terminal command and return the combined output."""
        timeout = min(max(timeout, 10), 3600)  # clamp: 10s–3600s
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=workdir,
                env=subprocess_env,
            )
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=float(timeout))
            except asyncio.TimeoutError:
                try:
                    process.terminate()
                    await process.wait()
                except Exception:
                    pass
                logger.warning("Bash command timed out after %ds: %.200s", timeout, command)
                return f"Error: Command timed out after {timeout} seconds."

            output = stdout.decode(errors="replace")
            err = stderr.decode(errors="replace")

            if err:
                output += f"\nSTDERR:\n{err}"

            return output.strip() if output.strip() else "(Command executed with no output)"

        except Exception as e:
            logger.error("Bash command failed: %s — %s", command[:200], e)
            return f"Error: {e}"

    return bash


TOOLS = [make_bash_tool(Path("."))]
TOOLS_FACTORY = make_bash_tool
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_builtin_tools/test_bash_env.py -v`
Expected: All PASS

**Step 5: Run existing tests to ensure no regressions**

Run: `uv run pytest tests/ -q --ignore=tests/api --ignore=tests/test_api -x`
Expected: All previously passing tests still pass

**Step 6: Commit**

```bash
git add src/everstaff/builtin_tools/bash.py tests/test_builtin_tools/test_bash_env.py
git commit -m "feat: Bash tool uses clean env, no longer inherits os.environ"
```

---

### Task 4: MCP Connection — SecretStore-Aware Environment Resolution

**Files:**
- Modify: `src/everstaff/mcp_client/connection.py` (accept optional SecretStore)
- Test: `tests/test_mcp_client/test_connection_env.py`

**Step 1: Write the failing test**

```python
# tests/test_mcp_client/test_connection_env.py
"""Tests for MCP connection environment resolution via SecretStore."""
import pytest
from unittest.mock import patch
from everstaff.core.secret_store import SecretStore
from everstaff.schema.agent_spec import MCPServerSpec
from everstaff.mcp_client.connection import MCPConnection


class TestMCPConnectionEnvResolution:
    def test_resolve_env_from_secret_store(self):
        """MCPServerSpec.env references should resolve from SecretStore."""
        store = SecretStore({"MY_TOKEN": "tok-123", "OTHER": "val"})
        spec = MCPServerSpec(
            name="test-server",
            command="echo",
            env={"TOKEN": "${MY_TOKEN}"},
            transport="stdio",
        )
        conn = MCPConnection(spec, secret_store=store)
        resolved = conn._resolve_spec_env()
        assert resolved == {"TOKEN": "tok-123"}

    def test_resolve_env_literal_values_unchanged(self):
        """Literal env values (no ${}) should pass through unchanged."""
        store = SecretStore({"X": "y"})
        spec = MCPServerSpec(
            name="test-server",
            command="echo",
            env={"LITERAL": "hello-world"},
            transport="stdio",
        )
        conn = MCPConnection(spec, secret_store=store)
        resolved = conn._resolve_spec_env()
        assert resolved == {"LITERAL": "hello-world"}

    def test_resolve_env_missing_secret_raises(self):
        """Referencing a missing secret should raise ValueError."""
        store = SecretStore({})
        spec = MCPServerSpec(
            name="test-server",
            command="echo",
            env={"TOKEN": "${MISSING_KEY}"},
            transport="stdio",
        )
        conn = MCPConnection(spec, secret_store=store)
        with pytest.raises(ValueError, match="MISSING_KEY"):
            conn._resolve_spec_env()

    def test_no_secret_store_falls_back_to_spec_env(self):
        """Without SecretStore, use spec.env as-is (backward compat)."""
        spec = MCPServerSpec(
            name="test-server",
            command="echo",
            env={"PLAIN": "value"},
            transport="stdio",
        )
        conn = MCPConnection(spec)  # no secret_store
        resolved = conn._resolve_spec_env()
        assert resolved == {"PLAIN": "value"}
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_mcp_client/test_connection_env.py -v`
Expected: FAIL — `MCPConnection.__init__() got an unexpected keyword argument 'secret_store'`

**Step 3: Modify connection.py**

Add to `MCPConnection.__init__`:

```python
import re

class MCPConnection:
    def __init__(self, spec: "MCPServerSpec", secret_store: "SecretStore | None" = None) -> None:
        self._spec = spec
        self._secret_store = secret_store
        self._exit_stack: AsyncExitStack | None = None

    def _resolve_spec_env(self) -> dict[str, str] | None:
        """Resolve ${VAR} references in spec.env using SecretStore.

        If no SecretStore is available, returns spec.env as-is.
        """
        if not self._spec.env:
            return None
        if self._secret_store is None:
            return dict(self._spec.env)

        resolved: dict[str, str] = {}
        for key, value in self._spec.env.items():
            def _sub(m: re.Match) -> str:
                name = m.group(1)
                val = self._secret_store.get(name)
                if val is None:
                    raise ValueError(
                        f"Secret '{name}' referenced in MCP server "
                        f"'{self._spec.name}' env is not available"
                    )
                return val
            resolved[key] = re.sub(r"\$\{([^}]+)\}", _sub, value)
        return resolved
```

Update `_build_transport` to use resolved env:

```python
    # In _build_transport, change line 70:
    # OLD: env=self._spec.env or None,
    # NEW:
    env=self._resolve_spec_env(),
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_mcp_client/test_connection_env.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/everstaff/mcp_client/connection.py tests/test_mcp_client/test_connection_env.py
git commit -m "feat: MCP connection resolves env vars from SecretStore"
```

---

### Task 5: Wire SecretStore Into RuntimeEnvironment and AgentBuilder

**Files:**
- Modify: `src/everstaff/builder/environment.py` (add secret_store property)
- Modify: `src/everstaff/builder/agent_builder.py` (pass SecretStore to tools and MCP)
- Test: `tests/test_builder/test_secret_store_wiring.py`

**Step 1: Write the failing test**

```python
# tests/test_builder/test_secret_store_wiring.py
"""Tests for SecretStore wiring through builder."""
import os
import pytest
from everstaff.core.secret_store import SecretStore
from everstaff.builder.environment import DefaultEnvironment


class TestSecretStoreWiring:
    def test_default_environment_has_secret_store(self):
        """DefaultEnvironment should provide a SecretStore."""
        env = DefaultEnvironment(sessions_dir="/tmp/test_sessions")
        store = env.secret_store
        assert isinstance(store, SecretStore)

    def test_default_environment_secret_store_from_environ(self):
        """DefaultEnvironment SecretStore should capture os.environ snapshot."""
        os.environ["_WIRING_TEST"] = "wired"
        try:
            env = DefaultEnvironment(sessions_dir="/tmp/test_sessions")
            assert env.secret_store.get("_WIRING_TEST") == "wired"
        finally:
            os.environ.pop("_WIRING_TEST", None)

    def test_custom_secret_store_injection(self):
        """Should allow injecting a custom SecretStore."""
        custom = SecretStore({"CUSTOM": "val"})
        env = DefaultEnvironment(sessions_dir="/tmp/test_sessions", secret_store=custom)
        assert env.secret_store.get("CUSTOM") == "val"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_builder/test_secret_store_wiring.py -v`
Expected: FAIL — `DefaultEnvironment() got an unexpected keyword argument 'secret_store'`

**Step 3: Modify environment.py**

Add `secret_store` property to `RuntimeEnvironment`:

```python
class RuntimeEnvironment:
    def __init__(self, config=None, channel_manager=None) -> None:
        # ... existing code ...
        pass

    @property
    def secret_store(self) -> "SecretStore":
        from everstaff.core.secret_store import SecretStore
        return SecretStore()  # base returns empty store
```

Add to `DefaultEnvironment.__init__`:

```python
class DefaultEnvironment(RuntimeEnvironment):
    def __init__(
        self,
        sessions_dir: str,
        session_id: str | None = None,
        config=None,
        channel_manager=None,
        mcp_pool=None,
        secret_store=None,
    ) -> None:
        super().__init__(config=config, channel_manager=channel_manager)
        self._sessions_dir = sessions_dir
        self._mcp_pool = mcp_pool
        self._secret_store = secret_store

    @property
    def secret_store(self):
        if self._secret_store is None:
            from everstaff.core.secret_store import SecretStore
            self._secret_store = SecretStore.from_environ()
        return self._secret_store
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_builder/test_secret_store_wiring.py -v`
Expected: All PASS

**Step 5: Modify agent_builder.py to pass SecretStore**

In `AgentBuilder._build_tool_registry()`, pass `env` from SecretStore to Bash tool:

Find the call to `loader.load(regular_tools, workdir=workdir)` and verify that `TOOLS_FACTORY` is called with `workdir`. The Bash `TOOLS_FACTORY = make_bash_tool` currently only accepts `workdir`. Since we added optional `env` parameter, we need to pass it through the ToolLoader.

The simplest approach: modify `_build_tool_registry` to pass a `tool_env` kwarg that gets forwarded to factory functions.

In `AgentBuilder._build_mcp_provider()`, pass SecretStore to MCPConnection:

Find where `MCPConnection(spec)` is constructed and add `secret_store=self._env.secret_store`.

*Note: The exact modifications depend on how ToolLoader calls TOOLS_FACTORY. Examine `src/everstaff/tools/loader.py` at line 62-67 to understand the factory call pattern, then thread `secret_store` through appropriately.*

**Step 6: Run full tests**

Run: `uv run pytest tests/ -q --ignore=tests/api --ignore=tests/test_api -x`
Expected: All previously passing tests still pass

**Step 7: Commit**

```bash
git add src/everstaff/builder/environment.py src/everstaff/builder/agent_builder.py tests/test_builder/test_secret_store_wiring.py
git commit -m "feat: wire SecretStore through RuntimeEnvironment and AgentBuilder"
```

---

## Phase 2: SandboxExecutor Interface

This phase defines the abstraction layer for sandbox backends.

### Task 6: SandboxExecutor Abstract Interface

**Files:**
- Create: `src/everstaff/sandbox/__init__.py`
- Create: `src/everstaff/sandbox/executor.py`
- Create: `src/everstaff/sandbox/models.py`
- Test: `tests/test_sandbox/test_executor_interface.py`

**Step 1: Write the failing test**

```python
# tests/test_sandbox/test_executor_interface.py
"""Tests for SandboxExecutor interface contracts."""
import pytest
from everstaff.sandbox.executor import SandboxExecutor
from everstaff.sandbox.models import SandboxCommand, SandboxResult, SandboxStatus


class TestSandboxModels:
    def test_sandbox_command_bash(self):
        cmd = SandboxCommand(type="bash", payload={"command": "ls", "timeout": 30})
        assert cmd.type == "bash"
        assert cmd.payload["command"] == "ls"

    def test_sandbox_result(self):
        result = SandboxResult(success=True, output="hello", exit_code=0)
        assert result.success is True
        assert result.output == "hello"

    def test_sandbox_status(self):
        status = SandboxStatus(alive=True, session_id="abc", uptime_seconds=10.0)
        assert status.alive is True


class TestSandboxExecutorIsAbstract:
    def test_cannot_instantiate(self):
        with pytest.raises(TypeError):
            SandboxExecutor()  # type: ignore
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_sandbox/test_executor_interface.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Write implementation**

```python
# src/everstaff/sandbox/__init__.py
"""Sandbox isolation for agent session execution."""

# src/everstaff/sandbox/models.py
"""Data models for sandbox communication."""
from __future__ import annotations
from pydantic import BaseModel


class SandboxCommand(BaseModel):
    type: str  # "bash", "mcp_start", "file_read", "file_write", etc.
    payload: dict


class SandboxResult(BaseModel):
    success: bool
    output: str = ""
    exit_code: int = 0
    error: str = ""


class SandboxStatus(BaseModel):
    alive: bool
    session_id: str
    uptime_seconds: float = 0.0


# src/everstaff/sandbox/executor.py
"""Abstract base class for sandbox executors."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from everstaff.sandbox.models import SandboxCommand, SandboxResult, SandboxStatus


class SandboxExecutor(ABC):
    """Abstract sandbox executor.

    Each session gets one executor. The executor manages an isolated
    environment where agent tools run.
    """

    @abstractmethod
    async def start(self, session_id: str) -> None:
        """Start the sandbox and complete secret injection."""

    @abstractmethod
    async def execute(self, command: "SandboxCommand") -> "SandboxResult":
        """Execute a command inside the sandbox."""

    @abstractmethod
    async def stop(self) -> None:
        """Destroy the sandbox and clean up resources."""

    @abstractmethod
    async def status(self) -> "SandboxStatus":
        """Return current sandbox status."""

    @property
    @abstractmethod
    def is_alive(self) -> bool:
        """Whether the sandbox is running."""
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_sandbox/test_executor_interface.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/everstaff/sandbox/ tests/test_sandbox/
git commit -m "feat: add SandboxExecutor abstract interface and models"
```

---

### Task 7: ExecutorManager — Lifecycle Management

**Files:**
- Create: `src/everstaff/sandbox/manager.py`
- Test: `tests/test_sandbox/test_manager.py`

**Step 1: Write the failing test**

```python
# tests/test_sandbox/test_manager.py
"""Tests for ExecutorManager lifecycle."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from everstaff.sandbox.manager import ExecutorManager
from everstaff.sandbox.executor import SandboxExecutor
from everstaff.sandbox.models import SandboxStatus
from everstaff.core.secret_store import SecretStore


class FakeExecutor(SandboxExecutor):
    """Concrete test executor."""
    def __init__(self):
        self._alive = False
        self._session_id = ""

    async def start(self, session_id: str) -> None:
        self._session_id = session_id
        self._alive = True

    async def execute(self, command):
        from everstaff.sandbox.models import SandboxResult
        return SandboxResult(success=True, output="ok")

    async def stop(self) -> None:
        self._alive = False

    async def status(self):
        return SandboxStatus(alive=self._alive, session_id=self._session_id)

    @property
    def is_alive(self) -> bool:
        return self._alive


@pytest.mark.asyncio
class TestExecutorManager:
    async def test_get_or_create_creates_new(self):
        factory = lambda: FakeExecutor()
        mgr = ExecutorManager(factory=factory, secret_store=SecretStore())
        executor = await mgr.get_or_create("session-1")
        assert executor.is_alive
        assert (await executor.status()).session_id == "session-1"

    async def test_get_or_create_returns_existing(self):
        factory = lambda: FakeExecutor()
        mgr = ExecutorManager(factory=factory, secret_store=SecretStore())
        e1 = await mgr.get_or_create("session-1")
        e2 = await mgr.get_or_create("session-1")
        assert e1 is e2

    async def test_destroy_removes_executor(self):
        factory = lambda: FakeExecutor()
        mgr = ExecutorManager(factory=factory, secret_store=SecretStore())
        executor = await mgr.get_or_create("session-1")
        await mgr.destroy("session-1")
        assert not executor.is_alive

    async def test_destroy_nonexistent_is_noop(self):
        factory = lambda: FakeExecutor()
        mgr = ExecutorManager(factory=factory, secret_store=SecretStore())
        await mgr.destroy("nonexistent")  # should not raise

    async def test_list_active(self):
        factory = lambda: FakeExecutor()
        mgr = ExecutorManager(factory=factory, secret_store=SecretStore())
        await mgr.get_or_create("s1")
        await mgr.get_or_create("s2")
        assert set(mgr.active_sessions) == {"s1", "s2"}

    async def test_destroy_all(self):
        factory = lambda: FakeExecutor()
        mgr = ExecutorManager(factory=factory, secret_store=SecretStore())
        await mgr.get_or_create("s1")
        await mgr.get_or_create("s2")
        await mgr.destroy_all()
        assert len(mgr.active_sessions) == 0
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_sandbox/test_manager.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Write implementation**

```python
# src/everstaff/sandbox/manager.py
"""ExecutorManager — manages sandbox executor lifecycle per session."""
from __future__ import annotations

import logging
from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from everstaff.core.secret_store import SecretStore
    from everstaff.sandbox.executor import SandboxExecutor

logger = logging.getLogger(__name__)


class ExecutorManager:
    """Create, cache, and recycle sandbox executors per session."""

    def __init__(
        self,
        factory: Callable[[], "SandboxExecutor"],
        secret_store: "SecretStore",
    ) -> None:
        self._factory = factory
        self._secret_store = secret_store
        self._executors: dict[str, "SandboxExecutor"] = {}

    async def get_or_create(self, session_id: str) -> "SandboxExecutor":
        if session_id in self._executors:
            executor = self._executors[session_id]
            if executor.is_alive:
                return executor
            # Dead executor — remove and recreate
            del self._executors[session_id]

        executor = self._factory()
        await executor.start(session_id)
        self._executors[session_id] = executor
        logger.info("Created sandbox executor for session %s", session_id)
        return executor

    async def destroy(self, session_id: str) -> None:
        executor = self._executors.pop(session_id, None)
        if executor is not None:
            await executor.stop()
            logger.info("Destroyed sandbox executor for session %s", session_id)

    async def destroy_all(self) -> None:
        for session_id in list(self._executors):
            await self.destroy(session_id)

    @property
    def active_sessions(self) -> list[str]:
        return list(self._executors.keys())
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_sandbox/test_manager.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/everstaff/sandbox/manager.py tests/test_sandbox/test_manager.py
git commit -m "feat: add ExecutorManager for sandbox lifecycle management"
```

---

### Task 8: ProcessSandbox — Local Subprocess Backend

**Files:**
- Create: `src/everstaff/sandbox/process_sandbox.py`
- Test: `tests/test_sandbox/test_process_sandbox.py`

**Step 1: Write the failing test**

```python
# tests/test_sandbox/test_process_sandbox.py
"""Tests for ProcessSandbox backend."""
import os
import pytest
from pathlib import Path
from everstaff.core.secret_store import SecretStore
from everstaff.sandbox.process_sandbox import ProcessSandbox
from everstaff.sandbox.models import SandboxCommand


@pytest.mark.asyncio
class TestProcessSandbox:
    async def test_start_and_stop(self, tmp_path):
        store = SecretStore({"KEY": "val"})
        sandbox = ProcessSandbox(workdir=tmp_path, secret_store=store)
        await sandbox.start("test-session")
        assert sandbox.is_alive
        await sandbox.stop()
        assert not sandbox.is_alive

    async def test_execute_bash_basic(self, tmp_path):
        store = SecretStore()
        sandbox = ProcessSandbox(workdir=tmp_path, secret_store=store)
        await sandbox.start("test-session")
        try:
            cmd = SandboxCommand(type="bash", payload={"command": "echo hello"})
            result = await sandbox.execute(cmd)
            assert result.success
            assert "hello" in result.output
        finally:
            await sandbox.stop()

    async def test_execute_bash_clean_env(self, tmp_path):
        """Bash commands in sandbox should NOT see parent os.environ."""
        os.environ["_SANDBOX_LEAK_TEST"] = "leaked"
        try:
            store = SecretStore({"_SANDBOX_LEAK_TEST": "leaked"})
            sandbox = ProcessSandbox(workdir=tmp_path, secret_store=store)
            await sandbox.start("test-session")
            cmd = SandboxCommand(type="bash", payload={"command": "echo $_SANDBOX_LEAK_TEST"})
            result = await sandbox.execute(cmd)
            assert "leaked" not in result.output
            await sandbox.stop()
        finally:
            os.environ.pop("_SANDBOX_LEAK_TEST", None)

    async def test_execute_bash_timeout(self, tmp_path):
        store = SecretStore()
        sandbox = ProcessSandbox(workdir=tmp_path, secret_store=store)
        await sandbox.start("test-session")
        try:
            cmd = SandboxCommand(type="bash", payload={"command": "sleep 60", "timeout": 2})
            result = await sandbox.execute(cmd)
            assert not result.success
            assert "timeout" in result.error.lower()
        finally:
            await sandbox.stop()

    async def test_status(self, tmp_path):
        store = SecretStore()
        sandbox = ProcessSandbox(workdir=tmp_path, secret_store=store)
        await sandbox.start("test-session")
        status = await sandbox.status()
        assert status.alive
        assert status.session_id == "test-session"
        await sandbox.stop()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_sandbox/test_process_sandbox.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Write implementation**

```python
# src/everstaff/sandbox/process_sandbox.py
"""ProcessSandbox — local subprocess-based sandbox backend."""
from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING

from everstaff.sandbox.executor import SandboxExecutor
from everstaff.sandbox.models import SandboxCommand, SandboxResult, SandboxStatus

if TYPE_CHECKING:
    from everstaff.core.secret_store import SecretStore

logger = logging.getLogger(__name__)


def _minimal_env() -> dict[str, str]:
    """Minimal environment for subprocess execution."""
    env: dict[str, str] = {}
    for key in ("PATH", "HOME", "USER", "LANG", "TERM"):
        val = os.environ.get(key)
        if val is not None:
            env[key] = val
    return env


class ProcessSandbox(SandboxExecutor):
    """Sandbox that runs commands as local subprocesses with clean env."""

    def __init__(self, workdir: Path, secret_store: "SecretStore") -> None:
        self._workdir = workdir
        self._secret_store = secret_store
        self._session_id: str = ""
        self._alive: bool = False
        self._started_at: float = 0.0
        self._subprocess_env = _minimal_env()

    async def start(self, session_id: str) -> None:
        self._session_id = session_id
        self._alive = True
        self._started_at = time.monotonic()
        self._workdir.mkdir(parents=True, exist_ok=True)
        logger.info("ProcessSandbox started for session %s at %s", session_id, self._workdir)

    async def execute(self, command: SandboxCommand) -> SandboxResult:
        if not self._alive:
            return SandboxResult(success=False, error="Sandbox not running")

        if command.type == "bash":
            return await self._exec_bash(command.payload)
        else:
            return SandboxResult(success=False, error=f"Unknown command type: {command.type}")

    async def _exec_bash(self, payload: dict) -> SandboxResult:
        cmd = payload.get("command", "")
        timeout = min(max(payload.get("timeout", 300), 10), 3600)

        try:
            process = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._workdir,
                env=self._subprocess_env,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=float(timeout)
                )
            except asyncio.TimeoutError:
                try:
                    process.terminate()
                    await process.wait()
                except Exception:
                    pass
                return SandboxResult(
                    success=False,
                    exit_code=-1,
                    error=f"Command timed out after {timeout} seconds",
                )

            output = stdout.decode(errors="replace")
            err = stderr.decode(errors="replace")
            if err:
                output += f"\n{err}"

            return SandboxResult(
                success=process.returncode == 0,
                output=output.strip(),
                exit_code=process.returncode or 0,
            )
        except Exception as e:
            return SandboxResult(success=False, error=str(e))

    async def stop(self) -> None:
        self._alive = False
        logger.info("ProcessSandbox stopped for session %s", self._session_id)

    async def status(self) -> SandboxStatus:
        uptime = time.monotonic() - self._started_at if self._alive else 0.0
        return SandboxStatus(
            alive=self._alive,
            session_id=self._session_id,
            uptime_seconds=uptime,
        )

    @property
    def is_alive(self) -> bool:
        return self._alive
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_sandbox/test_process_sandbox.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/everstaff/sandbox/process_sandbox.py tests/test_sandbox/test_process_sandbox.py
git commit -m "feat: add ProcessSandbox backend with clean env isolation"
```

---

## Phase 3: TLS Bootstrap (Future)

> This phase implements the ephemeral token + TLS encrypted channel for secret
> delivery when the sandbox runs as a separate process (full process isolation).
> Deferred until Phase 1-2 are validated in production.

**Outline:**
- Task 9: Ephemeral token generator (cryptographic random, TTL, single-use)
- Task 10: TLS server in Orchestrator (Unix socket, self-signed cert)
- Task 11: TLS client in Sandbox (connect with token, receive secrets)
- Task 12: Integration — sandbox process bootstraps via stdin token + TLS handshake

---

## Phase 4: Full Session-in-Sandbox Architecture (Future)

> This phase moves the entire AgentRuntime into the sandbox process.
> Requires IPC protocol for HITL events and subagent scheduling.

**Outline:**
- Task 13: IPC protocol definition (JSON-RPC over TLS Unix socket)
- Task 14: Sandbox runtime wrapper (runs AgentRuntime inside sandbox process)
- Task 15: HITL event forwarding (sandbox → orchestrator → channels)
- Task 16: Subagent delegation (sandbox → orchestrator → new sandbox)
- Task 17: Modify API layer to use ExecutorManager

---

## Phase 5: Docker Sandbox Backend (Future)

> Production-grade container isolation.

**Outline:**
- Task 18: DockerSandbox implementation (Docker SDK)
- Task 19: Container image for executor runtime
- Task 20: Idle timeout and container recycling
- Task 21: Integration tests with Docker

---

## Testing Strategy

| Phase | Test Type | What |
|-------|-----------|------|
| 1 | Unit | SecretStore, SandboxConfig, Bash clean env, MCP env resolution |
| 1 | Integration | Full agent run with `printenv` returns minimal env |
| 2 | Unit | SandboxExecutor interface, ExecutorManager lifecycle, ProcessSandbox |
| 3 | Integration | TLS bootstrap end-to-end |
| 4 | Integration | Full session in sandbox with HITL |
| 5 | Integration | Docker container lifecycle |

## Verification Checklist

After Phase 1 completion, verify:
- [ ] `uv run pytest tests/ -q` — no regressions
- [ ] Start a session, run `printenv` via Bash tool — should return minimal vars only
- [ ] Start a session with MCP server using `${SECRET}` in env — resolves from SecretStore
- [ ] `os.environ` in main process still has all original variables

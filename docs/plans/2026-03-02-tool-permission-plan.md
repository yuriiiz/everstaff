# Tool Permission System Redesign — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace auto-allow tool permissions with explicit allow + HITL escalation (once/session/permanent grant scopes).

**Architecture:** New `DynamicPermissionChecker` wraps global + agent static checkers, adds session grants layer, system tool bypass, and HITL fallback. `PermissionStage` handles grant persistence. A new `tool_permission` HITL request type carries tool metadata and 4 resolution options.

**Tech Stack:** Python 3.11+, Pydantic v2, FastAPI, pytest

**Design doc:** `docs/plans/2026-03-02-tool-permission-redesign.md`

---

### Task 1: Update `PermissionResult` — add `needs_hitl` field

**Files:**
- Modify: `src/everstaff/protocols.py:152-156`
- Test: `tests/test_permissions/test_rule_checker.py`

**Step 1: Write the failing test**

Add to `tests/test_permissions/test_rule_checker.py`:

```python
def test_permission_result_has_needs_hitl_field():
    from everstaff.protocols import PermissionResult
    result = PermissionResult(allowed=False, needs_hitl=True)
    assert result.needs_hitl is True

    # Default should be False
    result2 = PermissionResult(allowed=True)
    assert result2.needs_hitl is False
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_permissions/test_rule_checker.py::test_permission_result_has_needs_hitl_field -v`
Expected: FAIL — `TypeError: unexpected keyword argument 'needs_hitl'`

**Step 3: Write minimal implementation**

In `src/everstaff/protocols.py`, change the `PermissionResult` dataclass (lines 152-156):

```python
@dataclass
class PermissionResult:
    allowed: bool
    reason: str | None = None
    require_approval: bool = False  # Keep for now, remove in Task 3
    needs_hitl: bool = False
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_permissions/test_rule_checker.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/everstaff/protocols.py tests/test_permissions/test_rule_checker.py
git commit -m "feat(permissions): add needs_hitl field to PermissionResult"
```

---

### Task 2: Add `PermissionGrantScope` enum

**Files:**
- Modify: `src/everstaff/permissions/__init__.py`
- Test: `tests/test_permissions/test_rule_checker.py`

**Step 1: Write the failing test**

Add to `tests/test_permissions/test_rule_checker.py`:

```python
def test_permission_grant_scope_enum():
    from everstaff.permissions import PermissionGrantScope
    assert PermissionGrantScope.ONCE == "once"
    assert PermissionGrantScope.SESSION == "session"
    assert PermissionGrantScope.PERMANENT == "permanent"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_permissions/test_rule_checker.py::test_permission_grant_scope_enum -v`
Expected: FAIL — `ImportError: cannot import name 'PermissionGrantScope'`

**Step 3: Write minimal implementation**

In `src/everstaff/permissions/__init__.py`, add after the imports:

```python
from enum import Enum

class PermissionGrantScope(str, Enum):
    """Grant scope for tool permission HITL approvals."""
    ONCE = "once"
    SESSION = "session"
    PERMANENT = "permanent"
```

Update `__all__` to include `"PermissionGrantScope"`.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_permissions/test_rule_checker.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/everstaff/permissions/__init__.py tests/test_permissions/test_rule_checker.py
git commit -m "feat(permissions): add PermissionGrantScope enum"
```

---

### Task 3: Remove `require_approval` from `PermissionConfig` with deprecation

**Files:**
- Modify: `src/everstaff/permissions/__init__.py`
- Modify: `src/everstaff/protocols.py:152-156`
- Modify: `src/everstaff/permissions/rule_checker.py`
- Test: `tests/test_permissions/test_rule_checker.py`

**Step 1: Write the failing test**

Add to `tests/test_permissions/test_rule_checker.py`:

```python
import warnings

def test_permission_config_require_approval_deprecated():
    """require_approval should be accepted but emit a deprecation warning."""
    from everstaff.permissions import PermissionConfig
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        cfg = PermissionConfig(allow=["Read"], deny=[], require_approval=["Bash"])
        assert len(w) == 1
        assert "require_approval" in str(w[0].message).lower()
        assert "deprecated" in str(w[0].message).lower()
    # require_approval should be silently ignored (empty after init)
    assert not hasattr(cfg, "require_approval") or cfg.require_approval == []


def test_permission_config_no_warning_without_require_approval():
    from everstaff.permissions import PermissionConfig
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        cfg = PermissionConfig(allow=["Read"], deny=[])
        assert len(w) == 0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_permissions/test_rule_checker.py::test_permission_config_require_approval_deprecated -v`
Expected: FAIL — no deprecation warning emitted

**Step 3: Write minimal implementation**

In `src/everstaff/permissions/__init__.py`, update `PermissionConfig`:

```python
import warnings

class PermissionConfig(BaseModel):
    """Permission configuration with allow and deny lists.

    Rules use the format: ToolName(argument_pattern)
    - ToolName        — matches the tool with any arguments
    - ToolName(*)     — same as above
    - ToolName()      — matches only calls with no arguments
    - ToolName(foo:*) — glob match against canonical argument string
    """

    allow: list[str] = Field(default_factory=list)
    deny: list[str] = Field(default_factory=list)
    require_approval: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _deprecate_require_approval(self) -> "PermissionConfig":
        if self.require_approval:
            warnings.warn(
                "PermissionConfig.require_approval is deprecated and will be removed. "
                "Tools not in the allow list now automatically trigger HITL approval.",
                DeprecationWarning,
                stacklevel=4,
            )
            self.require_approval = []
        return self
```

Add `from pydantic import model_validator` to imports.

In `src/everstaff/protocols.py`, remove `require_approval` from `PermissionResult`:

```python
@dataclass
class PermissionResult:
    allowed: bool
    reason: str | None = None
    needs_hitl: bool = False
```

In `src/everstaff/permissions/rule_checker.py`, remove `require_approval` parameter and logic from `__init__` and `check()`. Update `merge()` accordingly.

**Step 4: Update existing tests**

Remove or update these tests in `tests/test_permissions/test_rule_checker.py`:
- `test_require_approval_wins_over_allow` — DELETE
- `test_deny_wins_over_require_approval` — DELETE (just test deny wins, no require_approval)
- `test_require_approval_with_strict_and_tool_not_in_allow` — DELETE
- `test_merge_combines_require_approval` — DELETE

In `tests/test_permissions/test_chained.py`:
- `test_global_require_approval_fires_before_agent_allow` — DELETE

In `tests/test_builder/test_permissions_wiring.py`:
- Remove `require_approval=[]` from all `PermissionConfig()` calls
- `test_build_permissions_global_deny_wins` — remove the `require_approval=["Bash"]` from global config and delete the `require_approval` assertion

Also update `test_non_strict_require_approval_fires` in `test_rule_checker.py` — DELETE.

**Step 5: Run all permission tests to verify**

Run: `pytest tests/test_permissions/ tests/test_builder/test_permissions_wiring.py -v`
Expected: ALL PASS

**Step 6: Commit**

```bash
git add src/everstaff/permissions/__init__.py src/everstaff/protocols.py \
  src/everstaff/permissions/rule_checker.py \
  tests/test_permissions/ tests/test_builder/test_permissions_wiring.py
git commit -m "feat(permissions): deprecate require_approval, remove from PermissionResult and RuleBasedChecker"
```

---

### Task 4: Refactor `RuleBasedChecker` — expose `matches_deny()` and `matches_allow()`

**Files:**
- Modify: `src/everstaff/permissions/rule_checker.py`
- Test: `tests/test_permissions/test_rule_checker.py`

**Step 1: Write the failing test**

Add to `tests/test_permissions/test_rule_checker.py`:

```python
def test_matches_deny_public():
    checker = RuleBasedChecker(allow=["Read"], deny=["Bash*"])
    assert checker.matches_deny("Bash", {}) is True
    assert checker.matches_deny("Bash_exec", {}) is True
    assert checker.matches_deny("Read", {}) is False


def test_matches_allow_public():
    checker = RuleBasedChecker(allow=["Read", "Glob*"], deny=[])
    assert checker.matches_allow("Read", {}) is True
    assert checker.matches_allow("Glob_find", {}) is True
    assert checker.matches_allow("Bash", {}) is False
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_permissions/test_rule_checker.py::test_matches_deny_public -v`
Expected: FAIL — `AttributeError: 'RuleBasedChecker' object has no attribute 'matches_deny'`

**Step 3: Write minimal implementation**

In `src/everstaff/permissions/rule_checker.py`, add two public methods and refactor `check()` to use them:

```python
def matches_deny(self, tool_name: str, args: dict[str, Any]) -> bool:
    """Return True if tool matches any deny pattern."""
    for pattern in self._deny:
        if fnmatch.fnmatch(tool_name, pattern):
            return True
    return False

def matches_allow(self, tool_name: str, args: dict[str, Any]) -> bool:
    """Return True if tool matches any allow pattern."""
    for pattern in self._allow:
        if fnmatch.fnmatch(tool_name, pattern):
            return True
    return False

def check(self, tool_name: str, args: dict[str, Any]) -> PermissionResult:
    if self.matches_deny(tool_name, args):
        return PermissionResult(
            allowed=False,
            reason=f"Matched deny rule for '{tool_name}'",
        )
    if self.matches_allow(tool_name, args):
        return PermissionResult(allowed=True)
    # default
    if self._strict:
        return PermissionResult(
            allowed=False,
            reason=f"'{tool_name}' not in allow list",
        )
    return PermissionResult(allowed=True)
```

**Step 4: Run all permission tests**

Run: `pytest tests/test_permissions/ -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/everstaff/permissions/rule_checker.py tests/test_permissions/test_rule_checker.py
git commit -m "refactor(permissions): expose matches_deny() and matches_allow() on RuleBasedChecker"
```

---

### Task 5: Create `DynamicPermissionChecker`

**Files:**
- Create: `src/everstaff/permissions/dynamic_checker.py`
- Test: `tests/test_permissions/test_dynamic_checker.py`

**Step 1: Write the failing test**

Create `tests/test_permissions/test_dynamic_checker.py`:

```python
import pytest
from everstaff.permissions.rule_checker import RuleBasedChecker
from everstaff.permissions.dynamic_checker import DynamicPermissionChecker


def _make_checker(
    global_allow=None, global_deny=None,
    agent_allow=None, agent_deny=None,
    session_grants=None,
    system_tools=None,
):
    global_checker = RuleBasedChecker(
        allow=global_allow or [], deny=global_deny or [],
    ) if (global_allow is not None or global_deny is not None) else None
    agent_checker = RuleBasedChecker(
        allow=agent_allow or [], deny=agent_deny or [],
    )
    return DynamicPermissionChecker(
        global_checker=global_checker,
        agent_checker=agent_checker,
        session_grants=session_grants or [],
        is_system_tool=lambda name: name in (system_tools or set()),
    )


def test_deny_always_wins():
    checker = _make_checker(agent_allow=["Bash"], agent_deny=["Bash"])
    result = checker.check("Bash", {})
    assert not result.allowed
    assert not result.needs_hitl


def test_global_deny_wins_over_agent_allow():
    checker = _make_checker(global_deny=["Bash"], agent_allow=["Bash"])
    result = checker.check("Bash", {})
    assert not result.allowed
    assert not result.needs_hitl


def test_agent_allow_permits():
    checker = _make_checker(agent_allow=["Read"])
    result = checker.check("Read", {})
    assert result.allowed


def test_global_allow_permits():
    checker = _make_checker(global_allow=["Read"])
    result = checker.check("Read", {})
    assert result.allowed


def test_union_allow():
    """Tool in global allow OR agent allow should be permitted."""
    checker = _make_checker(global_allow=["Read"], agent_allow=["Glob"])
    assert checker.check("Read", {}).allowed
    assert checker.check("Glob", {}).allowed


def test_session_grants_permit():
    checker = _make_checker(session_grants=["Bash"])
    result = checker.check("Bash", {})
    assert result.allowed


def test_system_tool_always_allowed():
    checker = _make_checker(system_tools={"request_human_input"})
    result = checker.check("request_human_input", {})
    assert result.allowed


def test_unknown_tool_triggers_hitl():
    checker = _make_checker(agent_allow=["Read"])
    result = checker.check("Bash", {})
    assert not result.allowed
    assert result.needs_hitl is True


def test_add_session_grant():
    checker = _make_checker()
    result = checker.check("Bash", {})
    assert result.needs_hitl

    checker.add_session_grant("Bash")
    result = checker.check("Bash", {})
    assert result.allowed


def test_deny_beats_session_grant():
    checker = _make_checker(agent_deny=["Bash"], session_grants=["Bash"])
    result = checker.check("Bash", {})
    assert not result.allowed
    assert not result.needs_hitl


def test_deny_beats_system_tool():
    """Explicit deny blocks even system tools."""
    checker = _make_checker(agent_deny=["request_human_input"], system_tools={"request_human_input"})
    result = checker.check("request_human_input", {})
    assert not result.allowed
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_permissions/test_dynamic_checker.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'everstaff.permissions.dynamic_checker'`

**Step 3: Write minimal implementation**

Create `src/everstaff/permissions/dynamic_checker.py`:

```python
"""DynamicPermissionChecker — wraps static checkers with session grants and HITL fallback."""
from __future__ import annotations

import fnmatch
from typing import Any, Callable

from everstaff.protocols import PermissionResult


class DynamicPermissionChecker:
    """Middleware permission checker.

    Resolution order:
    1. deny (global + agent) → reject
    2. allow (global OR agent, union) → permit
    3. session grants → permit
    4. system tool → permit
    5. fallback → needs_hitl=True
    """

    def __init__(
        self,
        global_checker: Any | None,  # RuleBasedChecker or None
        agent_checker: Any,           # RuleBasedChecker
        session_grants: list[str],
        is_system_tool: Callable[[str], bool],
    ) -> None:
        self._global = global_checker
        self._agent = agent_checker
        self._session_grants = list(session_grants)
        self._is_system = is_system_tool

    def check(self, tool_name: str, args: dict[str, Any]) -> PermissionResult:
        # 1. Deny check (global + agent)
        if self._global is not None and self._global.matches_deny(tool_name, args):
            return PermissionResult(allowed=False, reason=f"Denied by global policy for '{tool_name}'")
        if self._agent.matches_deny(tool_name, args):
            return PermissionResult(allowed=False, reason=f"Denied by agent policy for '{tool_name}'")

        # 2. Allow check (union: global OR agent)
        if self._global is not None and self._global.matches_allow(tool_name, args):
            return PermissionResult(allowed=True)
        if self._agent.matches_allow(tool_name, args):
            return PermissionResult(allowed=True)

        # 3. Session grants
        for pattern in self._session_grants:
            if fnmatch.fnmatch(tool_name, pattern):
                return PermissionResult(allowed=True)

        # 4. System tool bypass
        if self._is_system(tool_name):
            return PermissionResult(allowed=True)

        # 5. Not found → HITL
        return PermissionResult(
            allowed=False,
            needs_hitl=True,
            reason=f"'{tool_name}' not in allow list, requires human approval",
        )

    def add_session_grant(self, pattern: str) -> None:
        """Add a permission pattern for the current session."""
        if pattern not in self._session_grants:
            self._session_grants.append(pattern)

    @property
    def session_grants(self) -> list[str]:
        """Return current session grants (for persistence)."""
        return list(self._session_grants)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_permissions/test_dynamic_checker.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/everstaff/permissions/dynamic_checker.py tests/test_permissions/test_dynamic_checker.py
git commit -m "feat(permissions): add DynamicPermissionChecker with session grants and HITL fallback"
```

---

### Task 6: Add `extra_permissions` to session storage

**Files:**
- Modify: `src/everstaff/protocols.py` — `MemoryStore.save()` signature
- Modify: `src/everstaff/memory/file_store.py` — handle `extra_permissions` in save/load
- Modify: `src/everstaff/schema/memory.py` — add field to `Session` model
- Test: `tests/test_permissions/test_session_grants_persistence.py`

**Step 1: Write the failing test**

Create `tests/test_permissions/test_session_grants_persistence.py`:

```python
"""Test extra_permissions persistence in FileMemoryStore."""
import json
import pytest


@pytest.fixture
def tmp_memory(tmp_path):
    """Create a FileMemoryStore backed by tmp_path."""
    from everstaff.memory.file_store import FileMemoryStore
    from everstaff.storage.local import LocalFileStore
    store = LocalFileStore(str(tmp_path))
    return FileMemoryStore(store)


@pytest.mark.asyncio
async def test_save_and_load_extra_permissions(tmp_memory):
    """extra_permissions should be persisted alongside session data."""
    from everstaff.protocols import Message

    sid = "test-session-001"
    msgs = [Message(role="user", content="hello")]

    # Save with extra_permissions
    await tmp_memory.save(sid, msgs, extra_permissions=["Bash", "Write"])

    # Read back raw session.json
    raw = await tmp_memory._session_store.read(f"{sid}/session.json")
    data = json.loads(raw.decode())
    assert data.get("extra_permissions") == ["Bash", "Write"]


@pytest.mark.asyncio
async def test_extra_permissions_preserved_on_re_save(tmp_memory):
    """Re-saving without extra_permissions should preserve existing ones."""
    from everstaff.protocols import Message

    sid = "test-session-002"
    msgs = [Message(role="user", content="hello")]

    await tmp_memory.save(sid, msgs, extra_permissions=["Bash"])
    await tmp_memory.save(sid, msgs)  # no extra_permissions kwarg

    raw = await tmp_memory._session_store.read(f"{sid}/session.json")
    data = json.loads(raw.decode())
    assert data.get("extra_permissions") == ["Bash"]
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_permissions/test_session_grants_persistence.py -v`
Expected: FAIL — `TypeError: save() got an unexpected keyword argument 'extra_permissions'`

**Step 3: Write minimal implementation**

In `src/everstaff/protocols.py`, update `MemoryStore.save()` signature — add `extra_permissions: list[str] | None = None` parameter.

In `src/everstaff/memory/file_store.py`, update `save()`:
- Add `extra_permissions: list[str] | None = None` parameter
- In the payload dict, add: `"extra_permissions": extra_permissions if extra_permissions is not None else existing_meta.get("extra_permissions", [])`

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_permissions/test_session_grants_persistence.py -v`
Expected: ALL PASS

**Step 5: Also run existing tests to verify no breakage**

Run: `pytest tests/ -x -q --timeout=30`
Expected: ALL PASS

**Step 6: Commit**

```bash
git add src/everstaff/protocols.py src/everstaff/memory/file_store.py \
  tests/test_permissions/test_session_grants_persistence.py
git commit -m "feat(permissions): add extra_permissions to session storage"
```

---

### Task 7: Add `tool_permission` HITL request type

**Files:**
- Modify: `src/everstaff/protocols.py:180-190` — add `tool_name`, `tool_args` fields to `HitlRequest`
- Modify: `src/everstaff/schema/hitl_models.py` — update `HitlRequestPayload`
- Modify: `src/everstaff/schema/api_models.py` — add `grant_scope` to `HitlResolution`
- Modify: `src/everstaff/api/hitl.py` — add `grant_scope` to `HitlDecision`
- Test: `tests/test_permissions/test_tool_permission_hitl.py`

**Step 1: Write the failing test**

Create `tests/test_permissions/test_tool_permission_hitl.py`:

```python
"""Test tool_permission HITL request type."""


def test_hitl_request_tool_permission_fields():
    from everstaff.protocols import HitlRequest
    req = HitlRequest(
        hitl_id="test-123",
        type="tool_permission",
        prompt="Agent wants to execute 'Bash'",
        tool_name="Bash",
        tool_args={"command": "git status"},
        options=["reject", "approve_once", "approve_session", "approve_permanent"],
    )
    assert req.type == "tool_permission"
    assert req.tool_name == "Bash"
    assert req.tool_args == {"command": "git status"}


def test_hitl_resolution_grant_scope():
    from everstaff.schema.api_models import HitlResolution
    from datetime import datetime, timezone
    res = HitlResolution(
        decision="approved",
        grant_scope="session",
        resolved_at=datetime.now(timezone.utc),
    )
    assert res.grant_scope == "session"


def test_hitl_resolution_grant_scope_default_none():
    from everstaff.schema.api_models import HitlResolution
    from datetime import datetime, timezone
    res = HitlResolution(
        decision="approved",
        resolved_at=datetime.now(timezone.utc),
    )
    assert res.grant_scope is None
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_permissions/test_tool_permission_hitl.py -v`
Expected: FAIL — `TypeError: unexpected keyword argument 'tool_name'`

**Step 3: Write minimal implementation**

In `src/everstaff/protocols.py`, update `HitlRequest`:

```python
@dataclass
class HitlRequest:
    """Describes what the agent needs from a human."""
    hitl_id: str
    type: str           # "approve_reject" | "choose" | "provide_input" | "notify" | "tool_permission"
    prompt: str
    options: list[str] = field(default_factory=list)
    context: str = ""
    tool_call_id: str = ""
    origin_session_id: str = ""
    origin_agent_name: str = ""
    timeout_seconds: int = 86400
    # tool_permission fields
    tool_name: str = ""
    tool_args: dict[str, Any] = field(default_factory=dict)
```

In `src/everstaff/schema/api_models.py`, update `HitlResolution`:

```python
class HitlResolution(BaseModel):
    """Typed HITL resolution — replaces dict-based response field."""
    decision: str
    comment: Optional[str] = None
    resolved_at: datetime
    resolved_by: str = "human"
    grant_scope: Optional[str] = None  # "once" | "session" | "permanent" | None
```

In `src/everstaff/api/hitl.py`, update `HitlDecision`:

```python
class HitlDecision(BaseModel):
    decision: str
    comment: Optional[str] = None
    resolved_by: str = "human"
    grant_scope: Optional[str] = None  # For tool_permission type
```

In `src/everstaff/schema/hitl_models.py`, update `HitlRequestPayload`:

```python
class HitlRequestPayload(BaseModel):
    """The agent's request details."""
    type: str
    prompt: str
    options: list[str] = Field(default_factory=list)
    context: str = ""
    # tool_permission fields
    tool_name: str = ""
    tool_args: dict[str, Any] = Field(default_factory=dict)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_permissions/test_tool_permission_hitl.py -v`
Expected: ALL PASS

**Step 5: Run all tests to verify no breakage**

Run: `pytest tests/ -x -q --timeout=30`
Expected: ALL PASS

**Step 6: Commit**

```bash
git add src/everstaff/protocols.py src/everstaff/schema/api_models.py \
  src/everstaff/api/hitl.py src/everstaff/schema/hitl_models.py \
  tests/test_permissions/test_tool_permission_hitl.py
git commit -m "feat(hitl): add tool_permission HITL request type with grant_scope"
```

---

### Task 8: Update `PermissionStage` for HITL flow

**Files:**
- Modify: `src/everstaff/tools/stages.py`
- Test: `tests/test_permissions/test_permission_stage.py`

**Step 1: Write the failing test**

Create `tests/test_permissions/test_permission_stage.py`:

```python
"""Test PermissionStage with DynamicPermissionChecker HITL flow."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from everstaff.protocols import PermissionResult, HumanApprovalRequired, ToolResult
from everstaff.tools.stages import PermissionStage
from everstaff.tools.pipeline import ToolCallContext


def _make_ctx(tool_name="Bash", args=None, tool_call_id="tc-1"):
    ctx = MagicMock(spec=ToolCallContext)
    ctx.tool_name = tool_name
    ctx.args = args or {}
    ctx.tool_call_id = tool_call_id
    ctx.agent_context = MagicMock()
    ctx.agent_context.session_id = "sess-1"
    return ctx


@pytest.mark.asyncio
async def test_permission_stage_allowed():
    checker = MagicMock()
    checker.check.return_value = PermissionResult(allowed=True)
    stage = PermissionStage(checker)
    next_fn = AsyncMock(return_value=ToolResult(tool_call_id="tc-1", content="ok"))

    result = await stage(_make_ctx(), next_fn)
    assert result.content == "ok"
    next_fn.assert_awaited_once()


@pytest.mark.asyncio
async def test_permission_stage_denied():
    checker = MagicMock()
    checker.check.return_value = PermissionResult(allowed=False, reason="denied")
    stage = PermissionStage(checker)
    next_fn = AsyncMock()

    result = await stage(_make_ctx(), next_fn)
    assert result.is_error
    assert "denied" in result.content.lower()
    next_fn.assert_not_awaited()


@pytest.mark.asyncio
async def test_permission_stage_needs_hitl_raises():
    """When needs_hitl=True, PermissionStage raises HumanApprovalRequired."""
    checker = MagicMock()
    checker.check.return_value = PermissionResult(allowed=False, needs_hitl=True)
    stage = PermissionStage(checker)
    next_fn = AsyncMock()

    with pytest.raises(HumanApprovalRequired) as exc_info:
        await stage(_make_ctx(tool_name="Write", tool_call_id="tc-42"), next_fn)

    assert len(exc_info.value.requests) == 1
    req = exc_info.value.requests[0]
    assert req.type == "tool_permission"
    assert req.tool_name == "Write"
    next_fn.assert_not_awaited()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_permissions/test_permission_stage.py::test_permission_stage_needs_hitl_raises -v`
Expected: FAIL — `HumanApprovalRequired` not raised (current stage just returns error)

**Step 3: Write minimal implementation**

Update `src/everstaff/tools/stages.py`:

```python
"""Built-in pipeline stages: PermissionStage, ExecutionStage."""
from __future__ import annotations

from typing import Any, Awaitable, Callable
from uuid import uuid4

from everstaff.tools.pipeline import ToolCallContext
from everstaff.protocols import (
    HitlRequest,
    HumanApprovalRequired,
    PermissionChecker,
    ToolRegistry,
    ToolResult,
)


class PermissionStage:
    """Checks permissions before calling next.

    - Denied → return error ToolResult
    - Needs HITL → raise HumanApprovalRequired with tool_permission request
    - Allowed → call next
    """

    def __init__(self, checker: PermissionChecker) -> None:
        self._checker = checker

    async def __call__(
        self,
        ctx: ToolCallContext,
        next: Callable[[ToolCallContext], Awaitable[ToolResult]],
    ) -> ToolResult:
        result = self._checker.check(ctx.tool_name, ctx.args)

        if not result.allowed and not result.needs_hitl:
            return ToolResult(
                tool_call_id=ctx.tool_call_id,
                content=f"Permission denied for '{ctx.tool_name}': {result.reason}",
                is_error=True,
            )

        if result.needs_hitl:
            request = HitlRequest(
                hitl_id=str(uuid4()),
                type="tool_permission",
                prompt=f"Agent wants to execute tool '{ctx.tool_name}'",
                tool_name=ctx.tool_name,
                tool_args=ctx.args,
                tool_call_id=ctx.tool_call_id,
                options=["reject", "approve_once", "approve_session", "approve_permanent"],
            )
            raise HumanApprovalRequired([request])

        return await next(ctx)


class ExecutionStage:
    """Terminal stage: calls ToolRegistry.execute()."""

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    async def __call__(
        self,
        ctx: ToolCallContext,
        _next: Callable[[ToolCallContext], Awaitable[ToolResult]],
    ) -> ToolResult:
        return await self._registry.execute(ctx.tool_name, ctx.args, ctx.tool_call_id)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_permissions/test_permission_stage.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/everstaff/tools/stages.py tests/test_permissions/test_permission_stage.py
git commit -m "feat(permissions): PermissionStage raises HumanApprovalRequired for needs_hitl"
```

---

### Task 9: Add `AgentDefinitionWriter` protocol and YAML implementation

**Files:**
- Modify: `src/everstaff/protocols.py` — add `AgentDefinitionWriter` protocol
- Create: `src/everstaff/permissions/definition_writer.py` — YAML-based writer
- Test: `tests/test_permissions/test_definition_writer.py`

**Step 1: Write the failing test**

Create `tests/test_permissions/test_definition_writer.py`:

```python
"""Test AgentDefinitionWriter — writes permanent grants back to agent YAML."""
import pytest
import yaml


@pytest.fixture
def agent_yaml(tmp_path):
    """Create a minimal agent YAML for testing."""
    path = tmp_path / "TestAgent.yaml"
    path.write_text(yaml.dump({
        "agent_name": "TestAgent",
        "tools": ["Bash", "Read"],
        "permissions": {
            "allow": ["Read"],
            "deny": [],
        },
    }))
    return path


@pytest.mark.asyncio
async def test_yaml_writer_adds_allow_permission(agent_yaml):
    from everstaff.permissions.definition_writer import YamlAgentDefinitionWriter
    writer = YamlAgentDefinitionWriter(agents_dir=str(agent_yaml.parent))
    await writer.add_allow_permission("TestAgent", "Bash")

    data = yaml.safe_load(agent_yaml.read_text())
    assert "Bash" in data["permissions"]["allow"]
    assert "Read" in data["permissions"]["allow"]  # existing preserved


@pytest.mark.asyncio
async def test_yaml_writer_no_duplicate(agent_yaml):
    from everstaff.permissions.definition_writer import YamlAgentDefinitionWriter
    writer = YamlAgentDefinitionWriter(agents_dir=str(agent_yaml.parent))
    await writer.add_allow_permission("TestAgent", "Read")  # already in allow

    data = yaml.safe_load(agent_yaml.read_text())
    assert data["permissions"]["allow"].count("Read") == 1


@pytest.mark.asyncio
async def test_yaml_writer_creates_permissions_section(tmp_path):
    path = tmp_path / "SimpleAgent.yaml"
    path.write_text(yaml.dump({
        "agent_name": "SimpleAgent",
        "tools": ["Bash"],
    }))
    from everstaff.permissions.definition_writer import YamlAgentDefinitionWriter
    writer = YamlAgentDefinitionWriter(agents_dir=str(tmp_path))
    await writer.add_allow_permission("SimpleAgent", "Bash")

    data = yaml.safe_load(path.read_text())
    assert data["permissions"]["allow"] == ["Bash"]
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_permissions/test_definition_writer.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Write minimal implementation**

Add `AgentDefinitionWriter` protocol to `src/everstaff/protocols.py`:

```python
@runtime_checkable
class AgentDefinitionWriter(Protocol):
    async def add_allow_permission(self, agent_name: str, pattern: str) -> None: ...
```

Create `src/everstaff/permissions/definition_writer.py`:

```python
"""AgentDefinitionWriter implementations for persisting permanent permission grants."""
from __future__ import annotations

import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


class YamlAgentDefinitionWriter:
    """Write permission grants back to agent YAML files."""

    def __init__(self, agents_dir: str) -> None:
        self._agents_dir = Path(agents_dir)

    async def add_allow_permission(self, agent_name: str, pattern: str) -> None:
        path = self._agents_dir / f"{agent_name}.yaml"
        if not path.exists():
            logger.warning("Agent YAML not found: %s", path)
            return

        data = yaml.safe_load(path.read_text()) or {}
        permissions = data.setdefault("permissions", {})
        allow = permissions.setdefault("allow", [])

        if pattern not in allow:
            allow.append(pattern)
            path.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True))
            logger.info("Permanently granted '%s' to agent '%s'", pattern, agent_name)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_permissions/test_definition_writer.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/everstaff/protocols.py src/everstaff/permissions/definition_writer.py \
  tests/test_permissions/test_definition_writer.py
git commit -m "feat(permissions): add AgentDefinitionWriter protocol and YAML implementation"
```

---

### Task 10: Update HITL resolution to handle `grant_scope`

**Files:**
- Modify: `src/everstaff/hitl/resolve.py` — pass through `grant_scope`
- Modify: `src/everstaff/api/hitl.py` — forward `grant_scope` in resolution
- Test: `tests/test_permissions/test_hitl_grant_resolution.py`

**Step 1: Write the failing test**

Create `tests/test_permissions/test_hitl_grant_resolution.py`:

```python
"""Test HITL resolution with grant_scope for tool_permission requests."""
import json
import pytest
from datetime import datetime, timezone


@pytest.fixture
def session_store(tmp_path):
    from everstaff.storage.local import LocalFileStore
    return LocalFileStore(str(tmp_path))


@pytest.fixture
def session_with_tool_permission(session_store):
    """Create a session.json with a pending tool_permission HITL request."""
    import asyncio
    session_id = "test-session"
    data = {
        "session_id": session_id,
        "agent_name": "TestAgent",
        "status": "waiting_for_human",
        "hitl_requests": [{
            "hitl_id": "hitl-001",
            "tool_call_id": "tc-42",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "timeout_seconds": 86400,
            "status": "pending",
            "request": {
                "type": "tool_permission",
                "prompt": "Agent wants to execute 'Bash'",
                "tool_name": "Bash",
                "tool_args": {"command": "git status"},
            },
        }],
    }
    asyncio.get_event_loop().run_until_complete(
        session_store.write(
            f"{session_id}/session.json",
            json.dumps(data).encode(),
        )
    )
    return session_id


@pytest.mark.asyncio
async def test_resolve_tool_permission_with_grant_scope(session_store, session_with_tool_permission):
    from everstaff.hitl.resolve import resolve_hitl
    resolution = await resolve_hitl(
        session_id=session_with_tool_permission,
        hitl_id="hitl-001",
        decision="approved",
        grant_scope="session",
        file_store=session_store,
    )
    assert resolution.decision == "approved"
    assert resolution.grant_scope == "session"

    # Verify persisted
    raw = await session_store.read(f"{session_with_tool_permission}/session.json")
    data = json.loads(raw.decode())
    resp = data["hitl_requests"][0]["response"]
    assert resp["grant_scope"] == "session"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_permissions/test_hitl_grant_resolution.py -v`
Expected: FAIL — `TypeError: resolve_hitl() got an unexpected keyword argument 'grant_scope'`

**Step 3: Write minimal implementation**

In `src/everstaff/hitl/resolve.py`, update `resolve_hitl()`:

```python
async def resolve_hitl(
    session_id: str,
    hitl_id: str,
    decision: str,
    comment: str | None = None,
    resolved_by: str = "human",
    grant_scope: str | None = None,    # NEW
    *,
    file_store: "FileStore",
) -> "HitlResolution":
    from everstaff.schema.api_models import HitlResolution

    # ... (existing validation code unchanged) ...

    resolution = HitlResolution(
        decision=decision,
        comment=comment,
        resolved_at=datetime.now(timezone.utc),
        resolved_by=resolved_by,
        grant_scope=grant_scope,         # NEW
    )
    target["status"] = "resolved"
    target["response"] = resolution.model_dump(mode="json")

    await file_store.write(
        session_path,
        json.dumps(session_data, ensure_ascii=False, indent=2).encode(),
    )
    return resolution
```

In `src/everstaff/api/hitl.py`, update the `resolve_hitl` endpoint to forward `grant_scope`:

```python
await canonical_resolve(
    session_id=session_id,
    hitl_id=hitl_id,
    decision=decision.decision,
    comment=decision.comment,
    resolved_by=decision.resolved_by,
    grant_scope=decision.grant_scope,   # NEW
    file_store=store,
)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_permissions/test_hitl_grant_resolution.py -v`
Expected: ALL PASS

**Step 5: Run all tests**

Run: `pytest tests/ -x -q --timeout=30`
Expected: ALL PASS

**Step 6: Commit**

```bash
git add src/everstaff/hitl/resolve.py src/everstaff/api/hitl.py \
  tests/test_permissions/test_hitl_grant_resolution.py
git commit -m "feat(hitl): support grant_scope in HITL resolution for tool_permission"
```

---

### Task 11: Refactor `AgentBuilder._build_permissions()`

**Files:**
- Modify: `src/everstaff/builder/agent_builder.py:85-135, 240-297`
- Test: `tests/test_builder/test_permissions_wiring.py`

**Step 1: Write the failing test**

Replace/update `tests/test_builder/test_permissions_wiring.py`:

```python
"""Test AgentBuilder permission wiring with DynamicPermissionChecker."""
from unittest.mock import MagicMock

from everstaff.builder.agent_builder import AgentBuilder
from everstaff.schema.agent_spec import AgentSpec
from everstaff.permissions import PermissionConfig
from everstaff.permissions.dynamic_checker import DynamicPermissionChecker
from everstaff.core.config import FrameworkConfig
from everstaff.schema.model_config import ModelMapping


def _make_builder(agent_allow=None, agent_deny=None, global_allow=None, global_deny=None, tools=None):
    spec = AgentSpec(
        agent_name="TestAgent",
        tools=tools or [],
        permissions=PermissionConfig(allow=agent_allow or [], deny=agent_deny or []),
    )
    cfg = FrameworkConfig(
        model_mappings={"smart": ModelMapping(model_id="fake/m")},
        permissions=PermissionConfig(allow=global_allow or [], deny=global_deny or []),
    )
    mock_env = MagicMock()
    mock_env.config = cfg
    return AgentBuilder(spec=spec, env=mock_env)


def test_returns_dynamic_checker():
    builder = _make_builder(agent_allow=["Read"])
    checker = builder._build_permissions(system_tool_names=set())
    assert isinstance(checker, DynamicPermissionChecker)


def test_spec_tools_not_auto_allowed():
    """Tools in spec.tools should NOT be auto-injected into allow."""
    builder = _make_builder(tools=["Bash", "Read"])
    checker = builder._build_permissions(system_tool_names=set())
    # Bash is in tools but NOT in allow — should trigger HITL
    result = checker.check("Bash", {})
    assert not result.allowed
    assert result.needs_hitl


def test_explicit_allow_permits():
    builder = _make_builder(agent_allow=["Read"], tools=["Read", "Bash"])
    checker = builder._build_permissions(system_tool_names=set())
    assert checker.check("Read", {}).allowed
    assert checker.check("Bash", {}).needs_hitl


def test_global_deny_wins():
    builder = _make_builder(agent_allow=["Bash"], global_deny=["Bash"])
    checker = builder._build_permissions(system_tool_names=set())
    result = checker.check("Bash", {})
    assert not result.allowed
    assert not result.needs_hitl  # denied, not HITL


def test_global_allow_union():
    builder = _make_builder(global_allow=["Read"], agent_allow=["Glob"])
    checker = builder._build_permissions(system_tool_names=set())
    assert checker.check("Read", {}).allowed
    assert checker.check("Glob", {}).allowed


def test_system_tools_always_allowed():
    builder = _make_builder()
    checker = builder._build_permissions(system_tool_names={"request_human_input"})
    assert checker.check("request_human_input", {}).allowed


def test_session_grants_loaded():
    builder = _make_builder()
    checker = builder._build_permissions(
        system_tool_names=set(),
        session_grants=["Bash"],
    )
    assert checker.check("Bash", {}).allowed


def test_framework_config_has_permissions_field():
    cfg = FrameworkConfig()
    assert isinstance(cfg.permissions, PermissionConfig)
    assert cfg.permissions.deny == []
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_builder/test_permissions_wiring.py -v`
Expected: FAIL — `_build_permissions()` doesn't accept `system_tool_names` or `session_grants`

**Step 3: Write minimal implementation**

Refactor `src/everstaff/builder/agent_builder.py`:

In `_build_permissions()`:

```python
def _build_permissions(
    self,
    system_tool_names: set[str] | None = None,
    session_grants: list[str] | None = None,
):
    from everstaff.permissions.rule_checker import RuleBasedChecker
    from everstaff.permissions.dynamic_checker import DynamicPermissionChecker

    global_cfg = self._env.config.permissions

    # Global checker — only if global has any rules
    global_checker = None
    if global_cfg.allow or global_cfg.deny:
        global_checker = RuleBasedChecker(
            allow=global_cfg.allow,
            deny=global_cfg.deny,
        )

    # Agent checker — explicit allow/deny from spec only (NO auto-injection)
    agent_cfg = self._spec.permissions
    agent_checker = RuleBasedChecker(
        allow=list(agent_cfg.allow),
        deny=list(agent_cfg.deny),
    )

    return DynamicPermissionChecker(
        global_checker=global_checker,
        agent_checker=agent_checker,
        session_grants=session_grants or [],
        is_system_tool=lambda name: name in (system_tool_names or set()),
    )
```

Update the `build()` method where `_build_permissions()` is called (around line 114):

```python
# Collect system tool names (framework + provider)
system_tool_names = set(provider_tool_names)
# Add framework tool names
hitl_mode = getattr(self._spec, "hitl_mode", "on_request")
if hitl_mode != "never":
    system_tool_names.add("request_human_input")
if getattr(self._spec, "sub_agents", None):
    system_tool_names.add("delegate_task_to_subagent")
if getattr(self._spec, "workflow", None):
    system_tool_names.add("write_workflow_plan")
if getattr(self._spec, "enable_bootstrap", False):
    system_tool_names.update(("create_agent", "create_skill"))

# Load session grants from MemoryStore if resuming
session_grants = []
# TODO: Load from session metadata in Task 12

permissions = self._build_permissions(
    system_tool_names=system_tool_names,
    session_grants=session_grants,
)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_builder/test_permissions_wiring.py -v`
Expected: ALL PASS

**Step 5: Run full test suite**

Run: `pytest tests/ -x -q --timeout=30`
Expected: ALL PASS (if tests fail, fix imports and references to removed `ChainedPermissionChecker`)

**Step 6: Commit**

```bash
git add src/everstaff/builder/agent_builder.py tests/test_builder/test_permissions_wiring.py
git commit -m "refactor(builder): use DynamicPermissionChecker, remove spec.tools auto-injection"
```

---

### Task 12: Load session grants on session resume

**Files:**
- Modify: `src/everstaff/builder/agent_builder.py` — load `extra_permissions` from session metadata
- Modify: `src/everstaff/api/sessions.py` — pass session grants context on resume
- Test: `tests/test_builder/test_session_grants_loading.py`

**Step 1: Write the failing test**

Create `tests/test_builder/test_session_grants_loading.py`:

```python
"""Test that session grants are loaded from MemoryStore on session resume."""
import json
import pytest
from unittest.mock import MagicMock, AsyncMock


@pytest.mark.asyncio
async def test_session_grants_loaded_from_memory():
    """When resuming a session, extra_permissions from session.json should be loaded."""
    from everstaff.builder.agent_builder import AgentBuilder
    from everstaff.schema.agent_spec import AgentSpec
    from everstaff.permissions import PermissionConfig
    from everstaff.permissions.dynamic_checker import DynamicPermissionChecker

    spec = AgentSpec(agent_name="TestAgent", tools=["Bash"])

    # Mock environment with a file_store that returns session with extra_permissions
    mock_env = MagicMock()
    from everstaff.core.config import FrameworkConfig
    from everstaff.schema.model_config import ModelMapping
    mock_env.config = FrameworkConfig(model_mappings={"smart": ModelMapping(model_id="fake/m")})

    mock_file_store = AsyncMock()
    session_data = json.dumps({
        "session_id": "sess-123",
        "extra_permissions": ["Bash", "Write"],
    }).encode()
    mock_file_store.read = AsyncMock(return_value=session_data)
    mock_file_store.exists = AsyncMock(return_value=True)

    builder = AgentBuilder(spec=spec, env=mock_env, session_id="sess-123")

    # Load session grants
    grants = await builder._load_session_grants(mock_file_store)
    assert grants == ["Bash", "Write"]

    # Build permissions with loaded grants
    checker = builder._build_permissions(
        system_tool_names=set(),
        session_grants=grants,
    )
    assert isinstance(checker, DynamicPermissionChecker)
    assert checker.check("Bash", {}).allowed
    assert checker.check("Write", {}).allowed
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_builder/test_session_grants_loading.py -v`
Expected: FAIL — `AttributeError: '_build_session_grants' does not exist`

**Step 3: Write minimal implementation**

Add to `src/everstaff/builder/agent_builder.py`:

```python
async def _load_session_grants(self, file_store) -> list[str]:
    """Load extra_permissions from session.json if resuming."""
    if not self._session_id or file_store is None:
        return []
    try:
        import json
        path = f"{self._session_id}/session.json"
        if not await file_store.exists(path):
            return []
        raw = await file_store.read(path)
        data = json.loads(raw.decode())
        return data.get("extra_permissions", [])
    except Exception:
        return []
```

Update `build()` to call `_load_session_grants()` before `_build_permissions()`:

```python
# Load session grants from file_store if resuming
session_grants = await self._load_session_grants(file_store)

permissions = self._build_permissions(
    system_tool_names=system_tool_names,
    session_grants=session_grants,
)
```

Note: `file_store` must be resolved before calling `_build_permissions()`. Move the `file_store` resolution block (lines 140-144) above the permissions build.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_builder/test_session_grants_loading.py -v`
Expected: ALL PASS

**Step 5: Run full test suite**

Run: `pytest tests/ -x -q --timeout=30`
Expected: ALL PASS

**Step 6: Commit**

```bash
git add src/everstaff/builder/agent_builder.py tests/test_builder/test_session_grants_loading.py
git commit -m "feat(builder): load session grants from MemoryStore on resume"
```

---

### Task 13: Handle grant_scope in session resume flow

**Files:**
- Modify: `src/everstaff/api/sessions.py` — process `grant_scope` from resolved HITL
- Modify: `src/everstaff/core/runtime.py` — save `extra_permissions` in session on HITL
- Test: `tests/test_permissions/test_grant_scope_handling.py`

**Step 1: Write the failing test**

Create `tests/test_permissions/test_grant_scope_handling.py`:

```python
"""Test that grant_scope is processed correctly on session resume."""


def test_format_grant_decision_message():
    """When a tool_permission HITL is resolved, the decision message should include the grant scope."""
    from everstaff.api.sessions import _format_decision_message

    req = {
        "type": "tool_permission",
        "prompt": "Agent wants to execute 'Bash'",
        "tool_name": "Bash",
    }
    resp = {"decision": "approved", "grant_scope": "session"}
    msg = _format_decision_message(req, "approved", None)
    assert "approved" in msg.lower()
```

**Step 2: Run test to verify it fails or passes**

This test should already work if `_format_decision_message` exists and handles the general case. The real implementation work is in the resume flow.

**Step 3: Write implementation**

In `src/everstaff/api/sessions.py`, in the `_resume_session_task()` function, after reading resolved HITLs:

1. For each resolved HITL with type `"tool_permission"`:
   - If `grant_scope == "session"`: add `tool_name` to session's `extra_permissions`
   - If `grant_scope == "permanent"`: call `AgentDefinitionWriter.add_allow_permission()`
   - If `grant_scope == "once"` or rejected: no persistence

```python
# Process grant_scope for tool_permission resolutions
for item in resolved_hitls:
    req = item.get("request", {})
    resp = item.get("response", {})
    if req.get("type") == "tool_permission" and resp.get("decision") == "approved":
        grant_scope = resp.get("grant_scope", "once")
        tool_name = req.get("tool_name", "")
        if grant_scope == "session" and tool_name:
            await mem.save(session_id, messages, extra_permissions=[tool_name])
        elif grant_scope == "permanent" and tool_name:
            from everstaff.permissions.definition_writer import YamlAgentDefinitionWriter
            writer = YamlAgentDefinitionWriter(agents_dir=str(agents_dir))
            await writer.add_allow_permission(agent_name, tool_name)
            await mem.save(session_id, messages, extra_permissions=[tool_name])
```

**Step 4: Run test to verify**

Run: `pytest tests/test_permissions/test_grant_scope_handling.py -v`
Expected: PASS

**Step 5: Run full test suite**

Run: `pytest tests/ -x -q --timeout=30`
Expected: ALL PASS

**Step 6: Commit**

```bash
git add src/everstaff/api/sessions.py tests/test_permissions/test_grant_scope_handling.py
git commit -m "feat(permissions): process grant_scope in session resume flow"
```

---

### Task 14: Update config/YAML examples

**Files:**
- Modify: Builtin agent YAML examples (e.g., `src/everstaff/builtin_agents/Agent Creator.yaml`)
- Check: Any config.yaml templates

**Step 1: Update builtin agent YAML**

In any builtin agent YAMLs that have `permissions.require_approval`:
- Remove the `require_approval` field
- Add comments showing the new permission model

Example for `Agent Creator.yaml` permissions section:

```yaml
permissions:
  # Tools in the 'allow' list can execute without human approval.
  # Tools in 'tools' but NOT in 'allow' will trigger HITL approval.
  # User can approve: once, for the session, or permanently.
  allow:
    - Read
    - Glob
    - Grep
  deny:
    - "Bash(rm:*)"
  # require_approval: removed — tools not in allow automatically trigger HITL
```

**Step 2: Verify YAML loads without warnings**

```bash
python -c "
import yaml
from everstaff.schema.agent_spec import AgentSpec
# Load and validate a YAML to check no warnings
"
```

**Step 3: Commit**

```bash
git add src/everstaff/builtin_agents/
git commit -m "docs: update builtin agent YAMLs for new permission model"
```

---

### Task 15: Clean up — remove `ChainedPermissionChecker` if unused

**Files:**
- Check: `src/everstaff/permissions/chained.py` — verify no remaining imports
- Remove if unused
- Update: `tests/test_permissions/test_chained.py` — delete if checker removed

**Step 1: Search for remaining usages**

```bash
grep -r "ChainedPermissionChecker" src/ tests/
```

If no usages remain after Task 11, delete:
- `src/everstaff/permissions/chained.py`
- `tests/test_permissions/test_chained.py`

**Step 2: Run full test suite**

Run: `pytest tests/ -x -q --timeout=30`
Expected: ALL PASS

**Step 3: Commit**

```bash
git rm src/everstaff/permissions/chained.py tests/test_permissions/test_chained.py
git commit -m "chore: remove unused ChainedPermissionChecker"
```

---

### Task 16: Integration test — full permission HITL cycle

**Files:**
- Create: `tests/test_permissions/test_integration_permission_hitl.py`

**Step 1: Write integration test**

```python
"""Integration test: full tool permission HITL cycle."""
import pytest
from unittest.mock import MagicMock, AsyncMock

from everstaff.permissions.rule_checker import RuleBasedChecker
from everstaff.permissions.dynamic_checker import DynamicPermissionChecker
from everstaff.tools.stages import PermissionStage, ExecutionStage
from everstaff.tools.pipeline import ToolCallPipeline, ToolCallContext
from everstaff.protocols import HumanApprovalRequired, ToolResult


@pytest.mark.asyncio
async def test_full_hitl_cycle():
    """Tool not in allow → HITL raised → session grant added → re-check passes."""
    # 1. Build checker with Bash not allowed
    agent_checker = RuleBasedChecker(allow=["Read"], deny=[])
    checker = DynamicPermissionChecker(
        global_checker=None,
        agent_checker=agent_checker,
        session_grants=[],
        is_system_tool=lambda _: False,
    )

    # 2. First call: Bash triggers HITL
    result = checker.check("Bash", {})
    assert result.needs_hitl

    # 3. Simulate HITL resolution: user approves for session
    checker.add_session_grant("Bash")

    # 4. Second call: Bash is now allowed via session grant
    result = checker.check("Bash", {})
    assert result.allowed

    # 5. Read was always allowed
    assert checker.check("Read", {}).allowed

    # 6. Write still triggers HITL (not in any allow list)
    result = checker.check("Write", {})
    assert result.needs_hitl


@pytest.mark.asyncio
async def test_pipeline_hitl_raises():
    """Pipeline with DynamicPermissionChecker raises HITL for unallowed tool."""
    agent_checker = RuleBasedChecker(allow=["Read"], deny=[])
    checker = DynamicPermissionChecker(
        global_checker=None,
        agent_checker=agent_checker,
        session_grants=[],
        is_system_tool=lambda _: False,
    )

    mock_registry = MagicMock()
    mock_registry.execute = AsyncMock(return_value=ToolResult(tool_call_id="tc-1", content="ok"))

    pipeline = ToolCallPipeline([
        PermissionStage(checker),
        ExecutionStage(mock_registry),
    ])

    ctx = ToolCallContext(
        tool_name="Bash",
        args={"command": "ls"},
        agent_context=MagicMock(),
        tool_call_id="tc-1",
    )

    with pytest.raises(HumanApprovalRequired) as exc_info:
        await pipeline.execute(ctx)

    req = exc_info.value.requests[0]
    assert req.type == "tool_permission"
    assert req.tool_name == "Bash"

    # After session grant, pipeline should pass through
    checker.add_session_grant("Bash")
    result = await pipeline.execute(ctx)
    assert result.content == "ok"
```

**Step 2: Run integration test**

Run: `pytest tests/test_permissions/test_integration_permission_hitl.py -v`
Expected: ALL PASS

**Step 3: Run full test suite**

Run: `pytest tests/ -x -q --timeout=30`
Expected: ALL PASS

**Step 4: Commit**

```bash
git add tests/test_permissions/test_integration_permission_hitl.py
git commit -m "test: add integration test for full tool permission HITL cycle"
```

---

## Summary

| Task | Description | Key Files |
|------|-------------|-----------|
| 1 | Add `needs_hitl` to `PermissionResult` | `protocols.py` |
| 2 | Add `PermissionGrantScope` enum | `permissions/__init__.py` |
| 3 | Deprecate `require_approval` | `permissions/__init__.py`, `rule_checker.py`, `protocols.py` |
| 4 | Expose `matches_deny/allow` on `RuleBasedChecker` | `rule_checker.py` |
| 5 | Create `DynamicPermissionChecker` | `permissions/dynamic_checker.py` |
| 6 | Add `extra_permissions` to session storage | `protocols.py`, `memory/file_store.py` |
| 7 | Add `tool_permission` HITL type | `protocols.py`, `api_models.py`, `hitl_models.py` |
| 8 | Update `PermissionStage` for HITL | `tools/stages.py` |
| 9 | Add `AgentDefinitionWriter` | `protocols.py`, `permissions/definition_writer.py` |
| 10 | Handle `grant_scope` in HITL resolution | `hitl/resolve.py`, `api/hitl.py` |
| 11 | Refactor `AgentBuilder._build_permissions()` | `builder/agent_builder.py` |
| 12 | Load session grants on resume | `builder/agent_builder.py` |
| 13 | Process `grant_scope` in resume flow | `api/sessions.py` |
| 14 | Update config/YAML examples | Builtin agents |
| 15 | Remove unused `ChainedPermissionChecker` | `permissions/chained.py` |
| 16 | Integration test | `test_integration_permission_hitl.py` |

# Unified Logging Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Normalize all log statements to a consistent format and add lint rules to prevent regression.

**Architecture:** Pure refactoring — no new libraries, no new abstractions. Edit existing log statements in ~26 files, add third-party handler cleanup in `setup_logging()`, add a pre-commit lint script.

**Tech Stack:** Python stdlib `logging`, shell script for lint, pre-commit

---

### Task 1: Third-party handler cleanup in `setup_logging()`

**Files:**
- Modify: `src/everstaff/utils/logging.py:74-76`
- Test: `tests/test_utils/test_logging_setup.py`

**Step 1: Write the failing test**

Add to `tests/test_utils/test_logging_setup.py`:

```python
def test_third_party_handlers_cleared():
    """Third-party loggers must have no own handlers and propagate=True."""
    # Pre-add a handler to simulate a third-party library configuring its own
    litellm_logger = logging.getLogger("LiteLLM")
    fake_handler = logging.StreamHandler()
    litellm_logger.addHandler(fake_handler)
    litellm_logger.propagate = False

    from everstaff.utils.logging import setup_logging
    setup_logging(console=True, level="INFO")

    # After setup, handler should be cleared and propagate restored
    assert len(litellm_logger.handlers) == 0
    assert litellm_logger.propagate is True

    # Also check one from _NOISY_LOGGERS
    httpx_logger = logging.getLogger("httpx")
    assert len(httpx_logger.handlers) == 0
    assert httpx_logger.propagate is True
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_utils/test_logging_setup.py::test_third_party_handlers_cleared -v`
Expected: FAIL — handlers not cleared, propagate not set

**Step 3: Write minimal implementation**

In `src/everstaff/utils/logging.py`, add a `_LITELLM_LOGGERS` list after `_NOISY_LOGGERS` (line 29):

```python
_LITELLM_LOGGERS = ["LiteLLM", "LiteLLM Router", "LiteLLM Proxy"]
```

Replace lines 74-76 with:

```python
    # Suppress noisy third-party loggers and force them through our formatter
    for name in [*_NOISY_LOGGERS, *_LITELLM_LOGGERS]:
        lib_logger = logging.getLogger(name)
        lib_logger.setLevel(logging.WARNING)
        lib_logger.handlers.clear()
        lib_logger.propagate = True
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_utils/test_logging_setup.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/everstaff/utils/logging.py tests/test_utils/test_logging_setup.py
git commit -m "feat(logging): force third-party loggers through unified formatter"
```

---

### Task 2: Rename `_logger` to `logger` in all files

**Files:**
- Modify: `src/everstaff/api/__init__.py` (rename `_logger` on lines 14, 240 and all call sites)
- Modify: `src/everstaff/web_ui.py` (rename `_logger` on line 12 and all call sites)

**Step 1: Rename in `api/__init__.py`**

Find-replace all `_logger` → `logger` in the file. Note: line 240 has a second `_logger` inside `_ws_broadcast()` — this one uses a different logger name `"api.ws_broadcast"`. Rename to a distinct variable `_broadcast_logger` to avoid shadowing the module-level `logger`. Actually, per the design rules, all logger vars should be `logger`. Since this is a local-scope logger with a different name, rename to `broadcast_logger` (no underscore prefix).

- Line 14: `_logger = logging.getLogger(__name__)` → `logger = logging.getLogger(__name__)`
- Line 240: `_logger = logging.getLogger("api.ws_broadcast")` → `broadcast_logger = logging.getLogger("api.ws_broadcast")`
- All references to `_logger` in module scope → `logger`
- All references to `_logger` inside `_ws_broadcast()` → `broadcast_logger`

**Step 2: Rename in `web_ui.py`**

- Line 12: `_logger = logging.getLogger(__name__)` → `logger = logging.getLogger(__name__)`
- All references to `_logger` → `logger`

**Step 3: Run tests**

Run: `pytest tests/ -x -q`
Expected: ALL PASS (no behavioral change)

**Step 4: Commit**

```bash
git add src/everstaff/api/__init__.py src/everstaff/web_ui.py
git commit -m "refactor(logging): rename _logger to logger for consistency"
```

---

### Task 3: Remove manual prefixes — API subsystem

**Files:**
- Modify: `src/everstaff/api/ws.py`
- Modify: `src/everstaff/api/daemon.py`
- Modify: `src/everstaff/api/sessions.py`
- Modify: `src/everstaff/api/__init__.py`

**Step 1: Clean `api/ws.py`**

Remove all `[WS]` and directional arrows (`→`, `←`) from log messages. Convert any natural-language params to key=value. Examples:

- `logger.info("[WS] connect  session=%s  active=%d", ...)` → `logger.info("connect session=%s active=%d", ...)`
- `logger.info("[WS] ← user_message  session=%s  chars=%d", ...)` → `logger.info("user_message received session=%s chars=%d", ...)`
- `logger.info("[WS] disconnect  session=%s  active=%d", ...)` → `logger.info("disconnect session=%s active=%d", ...)`
- `logger.debug("[WS] user_message_echo broadcast failed: %s", ...)` → `logger.debug("user_message_echo broadcast failed err=%s", ...)`
- `logger.warning("[WS] ignoring user_message for session %s: ...")` → `logger.warning("ignoring user_message session=%s reason=...", ...)`

**Step 2: Clean `api/daemon.py`**

Remove all `[DaemonAPI]` prefixes and convert to key=value:

- `logger.debug("[DaemonAPI] GET /status — daemon not configured")` → `logger.debug("daemon not configured")`
- `logger.debug("[DaemonAPI] GET /status — %s", ...)` → `logger.debug("status=%s", ...)`
- `logger.debug("[DaemonAPI] GET /loops — %d loop(s)", ...)` → `logger.debug("loops count=%d", ...)`
- `logger.warning("[DaemonAPI] POST /reload — daemon not running")` → `logger.warning("reload requested but daemon not running")`
- `logger.info("[DaemonAPI] POST /reload — triggering hot reload")` → `logger.info("hot reload triggered")`
- `logger.info("[DaemonAPI] POST /reload — complete, %d loop(s) active", ...)` → `logger.info("hot reload complete loops=%d", ...)`

**Step 3: Clean `api/sessions.py`**

Remove all `[session]` and `[sandbox]` prefixes:

- `logger.info("[session] start  agent=%s  session=%s", ...)` → `logger.info("start agent=%s session=%s", ...)`
- `logger.info("[session] end agent=%s session=%s", ...)` → `logger.info("end agent=%s session=%s", ...)`
- `logger.info("[session] paused for HITL  agent=%s  session=%s", ...)` → `logger.info("paused for HITL agent=%s session=%s", ...)`
- `logger.error("[session] error agent=%s session=%s err=%s", ...)` → `logger.error("error agent=%s session=%s err=%s", ...)`
- And all other `[session]` / `[sandbox]` prefixed lines similarly

**Step 4: Clean `api/__init__.py`**

Remove `[WS]` prefixes from broadcast-related logs:

- `logger.debug("[WS] → %-22s  session=%s  recipients=%d", ...)` → `broadcast_logger.debug("broadcast type=%-22s session=%s recipients=%d", ...)`
- `logger.debug("[WS] send failed  session=%s  type=%s  err=%s", ...)` → `broadcast_logger.debug("send failed session=%s type=%s err=%s", ...)`

Also add `exc_info=True` to exception logs missing it (lines 54, 201, 265).

**Step 5: Run tests**

Run: `pytest tests/ -x -q`
Expected: ALL PASS

**Step 6: Commit**

```bash
git add src/everstaff/api/ws.py src/everstaff/api/daemon.py src/everstaff/api/sessions.py src/everstaff/api/__init__.py
git commit -m "refactor(logging): remove manual prefixes from API subsystem"
```

---

### Task 4: Remove manual prefixes — channels subsystem

**Files:**
- Modify: `src/everstaff/channels/lark_ws.py`
- Modify: `src/everstaff/channels/websocket.py`

**Step 1: Clean `channels/lark_ws.py`**

Remove all `[LARK-OUT]`, `[LARK-IN]`, `[LARK-CB]` prefixes:

- `logger.info("[LARK-OUT] POST %s\n  body=%s", ...)` → `logger.info("POST url=%s body=%s", ...)`
- `logger.info("[LARK-OUT] POST response status=%s\n  resp=%s", ...)` → `logger.info("POST response status=%s resp=%s", ...)`
- `logger.error("[LARK-OUT] send failed code=%s msg=%s", ...)` → `logger.error("send failed code=%s msg=%s", ...)`
- `logger.info("[LARK-CB] _parse: action.value=%s action.form_value=%s", ...)` → `logger.info("parse action value=%s form_value=%s", ...)`
- `logger.info("[LARK-IN] %s msg_id=%s trace_id=%s\n  payload=%s", ...)` → `logger.info("received type=%s msg_id=%s trace_id=%s payload=%s", ...)`
- And all other prefixed lines similarly

Also clean up `LarkWsChannel.method_name:` style prefixes — these are redundant since `__name__` already identifies the module.

**Step 2: Clean `channels/websocket.py`**

- `logger.info("[WS] → hitl_request  session=%s  hitl=%s  type=%s", ...)` → `logger.info("hitl_request session=%s hitl=%s type=%s", ...)`
- `logger.info("[WS] → hitl_resolved  hitl=%s  decision=%s  by=%s", ...)` → `logger.info("hitl_resolved hitl=%s decision=%s by=%s", ...)`

**Step 3: Run tests**

Run: `pytest tests/ -x -q`
Expected: ALL PASS

**Step 4: Commit**

```bash
git add src/everstaff/channels/lark_ws.py src/everstaff/channels/websocket.py
git commit -m "refactor(logging): remove manual prefixes from channels subsystem"
```

---

### Task 5: Remove manual prefixes — daemon subsystem

**Files:**
- Modify: `src/everstaff/daemon/agent_loop.py`
- Modify: `src/everstaff/daemon/think_engine.py`
- Modify: `src/everstaff/daemon/event_bus.py`
- Modify: `src/everstaff/daemon/sensor_manager.py`
- Modify: `src/everstaff/daemon/agent_daemon.py`
- Modify: `src/everstaff/daemon/sensors/internal.py`
- Modify: `src/everstaff/daemon/sensors/webhook.py`
- Modify: `src/everstaff/daemon/sensors/scheduler.py`
- Modify: `src/everstaff/daemon/sensors/file_watch.py`

**Step 1: Clean `daemon/agent_loop.py`**

Remove all `[Loop:%s]` prefixes. The `%s` was the agent name — move it to a key=value param:

- `logger.info("[Loop:%s] ▶ Cycle start — trigger=%s:%s, session=%s", self._name, ...)` → `logger.info("cycle start agent=%s trigger=%s:%s session=%s", self._name, ...)`
- `logger.info("[Loop:%s] ■ Cycle end — decision=%s, duration=%dms, session=%s", self._name, ...)` → `logger.info("cycle end agent=%s decision=%s duration=%dms session=%s", self._name, ...)`
- `logger.info("[Loop:%s] Loop started — tick_interval=%.0fs", self._name, ...)` → `logger.info("loop started agent=%s tick_interval=%.0fs", self._name, ...)`
- And all other `[Loop:%s]` lines — same pattern: remove prefix, add `agent=%s`

Also remove Unicode decoration (`▶`, `■`).

**Step 2: Clean `daemon/think_engine.py`**

Remove all `[Think:%s]` prefixes, add `agent=%s`:

- `logger.info("[Think:%s] Starting — trigger=%s:%s, pending=%d, goals=%d", self._name, ...)` → `logger.info("starting agent=%s trigger=%s:%s pending=%d goals=%d", self._name, ...)`
- And all other `[Think:%s]` lines similarly

**Step 3: Clean `daemon/event_bus.py`**

Remove all `[EventBus]` prefixes:

- `logger.info("[EventBus] Subscribed: '%s'", ...)` → `logger.info("subscribed target=%s", ...)`
- `logger.warning("[EventBus] No subscriber for target '%s' — event %s:%s dropped", ...)` → `logger.warning("no subscriber target=%s event=%s:%s dropped", ...)`
- And all other lines similarly

**Step 4: Clean `daemon/sensor_manager.py`**

Remove all `[SensorMgr]` prefixes:

- `logger.info("[SensorMgr] Registered sensor for agent '%s' (total=%d)", ...)` → `logger.info("registered sensor agent=%s total=%d", ...)`
- And all other lines similarly

**Step 5: Clean `daemon/agent_daemon.py`**

Remove `======` banner decorations:

- `logger.info("====== AgentDaemon starting ======")` → `logger.info("daemon starting")`
- `logger.info("====== AgentDaemon ready — %d agent(s) running ======", ...)` → `logger.info("daemon ready agents=%d", ...)`
- `logger.info("====== AgentDaemon shutting down ======")` → `logger.info("daemon shutting down")`
- `logger.info("====== AgentDaemon stopped ======")` → `logger.info("daemon stopped")`
- `logger.info("====== Hot reload triggered ======")` → `logger.info("hot reload triggered")`
- `logger.info("====== Hot reload complete ======")` → `logger.info("hot reload complete")`

**Step 6: Clean sensor files**

`sensors/internal.py` — remove `[InternalSensor:%s]`, add `agent=%s`
`sensors/webhook.py` — remove `[WebhookSensor:%s]`, add `agent=%s`
`sensors/scheduler.py` — remove `[Scheduler:%s]`, add `agent=%s`
`sensors/file_watch.py` — remove `[FileWatchSensor:%s]`, add `agent=%s`

**Step 7: Run tests**

Run: `pytest tests/ -x -q`
Expected: ALL PASS

**Step 8: Commit**

```bash
git add src/everstaff/daemon/
git commit -m "refactor(logging): remove manual prefixes from daemon subsystem"
```

---

### Task 6: Remove manual prefixes — sandbox subsystem

**Files:**
- Modify: `src/everstaff/sandbox/mixin.py`
- Modify: `src/everstaff/sandbox/entry.py`
- Modify: `src/everstaff/sandbox/proxy/tracer.py`
- Modify: `src/everstaff/sandbox/ipc/server_handler.py`

**Step 1: Clean `sandbox/mixin.py`**

Remove all `[ipc-drain]`, `[ipc-stop]`, `[ipc-conn:%x]` prefixes. The hex connection ID was useful context — keep as `conn=%x`:

- `logger.info("[ipc-drain] waiting (already_done=%s) session=%s", ...)` → `logger.info("drain waiting already_done=%s session=%s", ...)`
- `logger.warning("[ipc-conn:%x] handler STARTED session=%s", id(reader), ...)` → `logger.warning("handler started conn=%x session=%s", id(reader), ...)`
- `logger.warning("[ipc-conn:%x] EOF after %d messages session=%s", ...)` → `logger.warning("EOF conn=%x messages=%d session=%s", ...)`
- And all other lines similarly

**Step 2: Clean `sandbox/entry.py`**

Remove `[sandbox-entry]` prefixes:

- `logger.info("[sandbox-entry] yielded session_end for session %s", ...)` → `logger.info("yielded session_end session=%s", ...)`
- And other lines similarly

**Step 3: Clean `sandbox/proxy/tracer.py`**

Remove `[proxy-tracer]` prefixes:

- `logger.warning("[proxy-tracer] on_event kind=session_end session=%s pending=%d", ...)` → `logger.warning("on_event kind=session_end session=%s pending=%d", ...)`
- And other lines similarly

**Step 4: Clean `sandbox/ipc/server_handler.py`**

Remove `[ipc-handler]` prefixes:

- `logger.warning("[ipc-handler] tracer.event kind=session_end, tracer_type=%s", ...)` → `logger.warning("tracer.event kind=session_end tracer_type=%s", ...)`
- And other lines similarly

**Step 5: Run tests**

Run: `pytest tests/ -x -q`
Expected: ALL PASS

**Step 6: Commit**

```bash
git add src/everstaff/sandbox/
git commit -m "refactor(logging): remove manual prefixes from sandbox subsystem"
```

---

### Task 7: Fix exception logging without `exc_info`

**Files:**
- Modify: `src/everstaff/api/__init__.py` (lines 54, 201, 265)
- Modify: `src/everstaff/builtin_tools/bash.py` (line 87)

**Step 1: Add `exc_info=True` to all exception logs**

`api/__init__.py`:
- Line 54: `logger.warning("Failed to create Mem0Client for daemon: %s", _exc)` → add `, exc_info=True`
- Line 201: `logger.warning("Failed to create Mem0Client for sandbox: %s", _exc)` → add `, exc_info=True`
- Line 265: `broadcast_logger.debug("send failed ...", ...)` → add `, exc_info=True`

`builtin_tools/bash.py`:
- Line 87: `logger.error("Bash command failed: %s — %s", command[:200], e)` → `logger.error("bash command failed command=%s err=%s", command[:200], e, exc_info=True)`

**Step 2: Run tests**

Run: `pytest tests/ -x -q`
Expected: ALL PASS

**Step 3: Commit**

```bash
git add src/everstaff/api/__init__.py src/everstaff/builtin_tools/bash.py
git commit -m "fix(logging): add exc_info=True to all exception logs"
```

---

### Task 8: Add pre-commit lint hook

**Files:**
- Create: `scripts/check-log-format.sh`
- Create: `.pre-commit-config.yaml`

**Step 1: Create lint script**

Create `scripts/check-log-format.sh`:

```bash
#!/usr/bin/env bash
# Lint: detect logging anti-patterns in Python source files.
# Checks:
#   1. Manual [XXX] prefixes in log messages
#   2. _logger variable name (should be logger)

set -euo pipefail

errors=0

# Only check staged/changed Python files if arguments are provided,
# otherwise check all Python files under src/
if [ $# -gt 0 ]; then
    files=("$@")
else
    mapfile -t files < <(find src/everstaff -name '*.py' -not -path '*/builtin_skills/*')
fi

for f in "${files[@]}"; do
    [ -f "$f" ] || continue

    # Check 1: Manual [XXX] prefixes in log messages
    if grep -nE 'logger\.(info|debug|warning|error|exception)\(.*"\[' "$f" 2>/dev/null; then
        echo "ERROR: $f — log message contains manual [XXX] prefix (use __name__ instead)"
        errors=$((errors + 1))
    fi

    # Check 2: _logger variable name
    if grep -nE '_logger\s*=\s*logging\.getLogger' "$f" 2>/dev/null; then
        echo "ERROR: $f — use 'logger' not '_logger'"
        errors=$((errors + 1))
    fi
done

if [ "$errors" -gt 0 ]; then
    echo ""
    echo "Found $errors logging format violation(s). See docs/plans/2026-03-08-unified-logging-design.md for rules."
    exit 1
fi
```

**Step 2: Create `.pre-commit-config.yaml`**

```yaml
repos:
  - repo: local
    hooks:
      - id: check-log-format
        name: Check log format conventions
        entry: bash scripts/check-log-format.sh
        language: system
        types: [python]
        pass_filenames: true
```

**Step 3: Make script executable and test it**

Run: `chmod +x scripts/check-log-format.sh && bash scripts/check-log-format.sh`
Expected: Exit 0 (no violations found — we already fixed them all)

**Step 4: Commit**

```bash
git add scripts/check-log-format.sh .pre-commit-config.yaml
git commit -m "ci: add pre-commit hook for logging format enforcement"
```

---

### Task 9: Final verification

**Step 1: Run full test suite**

Run: `pytest tests/ -v`
Expected: ALL PASS

**Step 2: Run lint script on entire codebase**

Run: `bash scripts/check-log-format.sh`
Expected: Exit 0

**Step 3: Spot-check log output**

Run: `python -c "from everstaff.utils.logging import setup_logging; setup_logging(level='DEBUG'); import logging; logging.getLogger('everstaff.api.ws').info('connect session=%s active=%d', 'abc', 3)"`
Expected: `2026-03-08T... INFO     everstaff.api.ws — connect session=abc active=3`

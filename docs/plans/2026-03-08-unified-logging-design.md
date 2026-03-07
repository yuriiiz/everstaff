# Unified Logging Design

**Date:** 2026-03-08
**Goal:** Normalize log format across the project + add lint rules to prevent regression

## Logging Rules

1. **No manual prefixes** — Remove all `[XXX]` style prefixes from log messages (e.g. `[WS]`, `[LARK-OUT]`, `[EventBus]`, `[ipc-conn:x]`). Rely entirely on `logging.getLogger(__name__)` module path for component identification.

2. **Parameters use `key=value`** — All log parameters must use `key=value` format.
   - Good: `logger.info("cycle started trigger=%s phase=%s", trigger, phase)`
   - Bad: `logger.info("starting cycle with %s in %s", trigger, phase)`

3. **Exceptions always include traceback** — Use `logger.exception()` or `logger.error(..., exc_info=True)`. Never log only `str(e)` without traceback.

4. **Logger variable name is `logger`** — Not `_logger`. Uniform across all modules.

## Third-Party Library Log Format Unification

In `setup_logging()`, force all third-party loggers (including LiteLLM) to use our formatter:

```python
for name in _NOISY_LOGGERS:
    lib_logger = logging.getLogger(name)
    lib_logger.handlers.clear()
    lib_logger.propagate = True

# LiteLLM has multiple loggers
for name in ("LiteLLM", "LiteLLM Router", "LiteLLM Proxy"):
    lib_logger = logging.getLogger(name)
    lib_logger.handlers.clear()
    lib_logger.propagate = True
```

## Lint Prevention (pre-commit hook)

**File:** `scripts/check-log-format.sh`

**Checks:**
1. Log messages starting with `[` (manual prefix detection): pattern `logger\.(info|debug|warning|error|exception)\(.*"\[`
2. `_logger = logging.getLogger` naming violation

**Not checked (too high false-positive risk):**
- `key=value` format in parameters
- `exc_info` usage

## Change Scope

| Subsystem | Files | Changes |
|-----------|-------|---------|
| channels (lark, ws, manager) | ~5 | Remove `[LARK-OUT]` `[LARK-IN]` etc., key=value |
| daemon (agent_loop, event_bus, agent_daemon, etc.) | ~8 | Remove `[Loop:x]` `[EventBus]` etc., key=value |
| api (ws, sessions, daemon, __init__) | ~5 | Remove `[WS]` `[DaemonAPI]`, key=value |
| sandbox (mixin, entry, ipc) | ~4 | Remove `[ipc-conn:x]` `[sandbox-entry]`, key=value |
| llm (litellm_client, secret_bridge) | ~2 | key=value |
| tracing (console) | ~1 | Remove `[session_id]`, key=value |
| utils/logging.py | 1 | Add third-party handler cleanup |
| `_logger` -> `logger` rename | all files using `_logger` | Pure rename |

**New files:**
- `scripts/check-log-format.sh` — lint script
- `.pre-commit-config.yaml` entry (append if exists)

**Not changed:**
- `setup_logging()` format string — stays as-is
- `cli.py` print() calls — user-facing interactive output
- `builtin_skills/` print(file=sys.stderr) — script output
- Third-party noise suppression levels — stays WARNING

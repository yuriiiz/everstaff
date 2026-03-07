# Simplify HITL Configuration

## Problem

Two unnecessary complexities in the current HITL configuration:

1. **Per-trigger `hitl_channels`** — `TriggerConfig.hitl_channels` allows each trigger to have its own HITL channels, but this granularity is unused and adds complexity to channel resolution logic. Agent-level `hitl_channels` is sufficient.

2. **`hitl_mode: "always"`** — Claims to require human approval before every action, but enforcement is purely prompt-based (system prompt injection). No runtime mechanism blocks tool calls without prior approval. The LLM can ignore the prompt and call tools directly, making this mode unreliable.

## Changes

### 1. Remove `TriggerConfig.hitl_channels`

- Remove `hitl_channels` field from `TriggerConfig`
- Simplify `AgentLoop._resolve_channels`: use only `AgentSpec.hitl_channels` (agent-level), fallback to global `ChannelManager`
- Remove `agent_hitl_channels` parameter from `AgentLoop.__init__` (no longer needed as a separate param)
- Update `AgentDaemon` to stop passing `agent_hitl_channels`
- Remove per-trigger HITL channel UI in `AgentStore.jsx`
- Update related tests

### 2. Remove `hitl_mode: "always"`

- Change `AgentSpec.hitl_mode` type from `Literal["always", "on_request", "notify", "never"]` to `Literal["on_request", "notify", "never"]`
- Remove `"always"` from `_VALID_MODES` in `hitl_tool.py`
- Remove `always` branch in `RequestHumanInputTool.get_prompt_injection()`
- Remove `"always"` option from frontend HITL mode selector
- Update related tests

### What stays unchanged

- `AgentSpec.hitl_channels` — agent-level HITL channel configuration
- `AgentSpec.hitl_mode` with `"on_request" | "notify" | "never"` — these modes work correctly
- Permission-based HITL (`DynamicPermissionChecker.needs_hitl`) — separate concern, works independently of `hitl_mode`

## Affected files

| Area | File | Change |
|------|------|--------|
| Schema | `src/everstaff/schema/autonomy.py` | Remove `hitl_channels` from `TriggerConfig` |
| Schema | `src/everstaff/schema/agent_spec.py` | Remove `"always"` from `hitl_mode` Literal |
| Daemon | `src/everstaff/daemon/agent_loop.py` | Simplify `_resolve_channels`, remove `agent_hitl_channels` param |
| Daemon | `src/everstaff/daemon/agent_daemon.py` | Stop passing `agent_hitl_channels` |
| Tool | `src/everstaff/tools/hitl_tool.py` | Remove `"always"` mode |
| Frontend | `web/src/pages/AgentStore.jsx` | Remove per-trigger HITL channel UI, remove `"always"` option |
| Tests | `tests/test_schema/test_hitl_channel_ref.py` | Update trigger channel tests |
| Tests | `tests/test_daemon/test_agent_loop.py` | Remove/update trigger channel tests |
| Tests | `tests/test_daemon/test_agent_daemon.py` | Update channel passing test |
| Tests | `tests/test_workflow/test_workflow_spec.py` | Remove `always` mode test |
| Tests | `tests/test_builder/test_permissions_build.py` | No change (uses `on_request`/`never`) |
| Docs | `README.md`, `docs/` | Remove `always` references if any |

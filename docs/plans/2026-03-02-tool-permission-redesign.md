# Tool Permission System Redesign

## Summary

Redesign the agent tool permission system from "auto-allow everything configured" to "explicit permission required with HITL escalation." Regular tools (from `spec.tools`) are no longer auto-added to the allow list. Tools not explicitly allowed trigger a human-in-the-loop (HITL) approval flow with three grant scopes: once, session, permanent.

## Motivation

The current system auto-injects all configured tools into the allow list, providing no runtime permission control. This means agents can execute any tool in their `spec.tools` without oversight. The new design gives operators fine-grained control over which tools are pre-approved and which require human approval at runtime.

## Design

### Permission Model

**Simplified `PermissionConfig`:**
```python
class PermissionConfig(BaseModel):
    allow: list[str] = Field(default_factory=list)  # Explicitly allowed patterns
    deny: list[str] = Field(default_factory=list)    # Explicitly denied patterns
    # require_approval: REMOVED
```

**Resolution order:**
1. **deny match** (global OR agent) -> reject, no appeal
2. **allow match** (global OR agent, union) -> permit
3. **session grant match** -> permit
4. **system-defined tool** -> permit (always auto-allowed)
5. **none of the above** -> trigger HITL

**Global + Agent interaction:** Union model. If a tool is in EITHER global allow or agent allow, it's permitted. Deny always wins over allow at any level.

### Tool Categories

| Category | Examples | Auto-allowed? |
|----------|----------|---------------|
| **Framework tools** | `request_human_input`, `delegate_task_to_subagent`, `write_workflow_plan`, `create_agent`, `create_skill` | Yes (system) |
| **Provider tools** | Skill tools, `search_knowledge`, `get_knowledge_document`, MCP tools, sub-agent tool | Yes (system) |
| **Regular tools** | Tools from `spec.tools` loaded via `ToolLoader` | **No** (must be in allow list or HITL) |

Regular tools are still registered in the `ToolRegistry` (so the agent CAN call them), but execution requires explicit permission.

### DynamicPermissionChecker

New middleware checker wrapping static checkers:

```python
class DynamicPermissionChecker(PermissionChecker):
    def __init__(
        self,
        global_checker: RuleBasedChecker | None,
        agent_checker: RuleBasedChecker,
        session_grants: list[str],
        is_system_tool: Callable[[str], bool],
    ):
        ...

    def check(self, tool_name: str, args: dict) -> PermissionResult:
        # 1. Deny check (global + agent)
        # 2. Allow check (global OR agent, union)
        # 3. Session grants check
        # 4. System tool check
        # 5. Fallback: needs_hitl=True

    def add_session_grant(self, pattern: str):
        """Add a grant for the current session (in-memory)."""
        self._session_grants.append(pattern)
```

**Changes to existing types:**
- `RuleBasedChecker`: expose `matches_deny()` and `matches_allow()` as public methods
- `PermissionResult`: add `needs_hitl: bool = False` field

### HITL Request Type: `tool_permission`

New HITL request type dedicated to tool permission approval:

```python
class HitlRequestType(str, Enum):
    APPROVE_REJECT = "approve_reject"
    CHOOSE = "choose"
    PROVIDE_INPUT = "provide_input"
    NOTIFY = "notify"
    TOOL_PERMISSION = "tool_permission"  # NEW

class PermissionGrantScope(str, Enum):
    ONCE = "once"
    SESSION = "session"
    PERMANENT = "permanent"
```

**HITL request payload:**
```python
HitlRequest(
    type="tool_permission",
    prompt=f"Agent wants to execute '{tool_name}'",
    tool_name=tool_name,
    tool_args=args,
    tool_call_id=tool_call_id,
    options=["reject", "approve_once", "approve_session", "approve_permanent"],
)
```

**Resolution payload:**
```json
{
    "approved": true,
    "grant_scope": "session",
    "response": "optional note"
}
```

### PermissionStage Changes

`PermissionStage` gains new dependencies and handles HITL resolution:

```python
class PermissionStage:
    def __init__(
        self,
        checker: DynamicPermissionChecker,
        session_id: str,
        agent_definition_writer: AgentDefinitionWriter,
        memory_store: MemoryStore,
    ):
        ...
```

On `needs_hitl=True`:
1. Build `HitlRequest(type="tool_permission", ...)`
2. Raise `HumanApprovalRequired([request])`
3. On resolution:
   - **Rejected** -> return error `ToolResult`
   - **Approved (once)** -> execute tool, no persistence
   - **Approved (session)** -> `checker.add_session_grant(pattern)`, persist to MemoryStore, execute
   - **Approved (permanent)** -> write to agent definition via `AgentDefinitionWriter`, also add session grant, execute

### Session Grants Persistence

Stored in `MemoryStore` alongside session metadata:

```python
# New field in session save:
extra_permissions: list[str] | None = None
```

- **Write:** After session-scoped grant, call `memory_store.update_extra_permissions(session_id, pattern)`
- **Load:** At session resume, `AgentBuilder` reads `extra_permissions` from session metadata and passes to `DynamicPermissionChecker`

### Permanent Grant Persistence

```python
class AgentDefinitionWriter(Protocol):
    async def add_allow_permission(self, agent_uuid: str, pattern: str) -> None:
        """Write a permission pattern to the agent's allow list.
        For YAML agents: modify the YAML file.
        For DB agents: update the DB record.
        """
        ...
```

Target depends on where the agent is defined (YAML file vs DB).

### Daemon HITL Broadcasting

- Only daemon-sourced sessions broadcast `tool_permission` HITL requests to channels
- Non-daemon sessions use the existing `HumanApprovalRequired` raise mechanism (direct resolution)
- This is existing infrastructure -- no new broadcast code needed, just new request type rendering in channels

### AgentBuilder Changes

**Current `_build_permissions()`:**
1. Build global checker (strict=False)
2. Build agent checker (strict=True)
3. Auto-inject `spec.tools` into allow
4. Auto-inject provider tools into allow
5. Auto-inject framework tools into allow

**New `_build_permissions()`:**
1. Build global checker -- deny list only
2. Build agent checker -- deny + explicit allow from spec (NO auto-injection of spec.tools)
3. Collect system tool names (framework + provider) into a set
4. Load session grants from MemoryStore (if resuming)
5. Build `DynamicPermissionChecker(global, agent, session_grants, is_system_tool)`
6. Build `PermissionStage` with dynamic checker + MemoryStore + AgentDefinitionWriter

## Usage Examples

### Agent YAML (permissions section)

```yaml
agent_name: My Agent
tools:
  - Bash
  - Read
  - Write
  - Glob

permissions:
  # Explicitly allow these tools without HITL:
  allow:
    - Read
    - Glob
    - "Bash(git:*)"     # Allow Bash only for git commands
  # Explicitly deny these tools (no appeal):
  deny:
    - "Bash(rm:*)"      # Never allow rm commands

  # If a tool is in 'tools' but NOT in 'allow', it will trigger HITL
  # at runtime. User can approve once, for session, or permanently.
  #
  # In this example:
  #   - Read, Glob: pre-approved
  #   - Bash(git:*): pre-approved for git commands
  #   - Bash(rm:*): always denied
  #   - Bash(other): triggers HITL
  #   - Write: triggers HITL (in tools but not in allow)
```

### Global config.yaml (permissions section)

```yaml
permissions:
  # Global allow: pre-approved for ALL agents (union with agent allow)
  allow:
    - Read     # All agents can read files without HITL
    - Glob     # All agents can glob without HITL
  # Global deny: denied for ALL agents (overrides agent allow)
  deny:
    - "Bash(rm -rf:*)"  # No agent can rm -rf

  # If global allow is empty/omitted:
  #   -> No global pre-approvals. Each agent's own allow list
  #      (or HITL) determines what's permitted.
  #
  # If global allow has entries:
  #   -> Those tools are pre-approved for all agents (union model)
  #      unless explicitly denied at agent or global level.
```

## Migration

1. **`require_approval` removal:** Add pydantic validator that emits deprecation warning and ignores `require_approval` entries (they naturally become HITL-triggering under the new model).
2. **Existing agents:** Agents with tools but no explicit `allow` will start triggering HITL for every tool call. This is intentional.
3. **Config examples:** Update `config.yaml` and agent YAML templates with commented usage examples.

## Files to Modify

| File | Change |
|------|--------|
| `src/everstaff/permissions/__init__.py` | Remove `require_approval`, add `PermissionGrantScope` |
| `src/everstaff/permissions/rule_checker.py` | Expose `matches_deny()`, `matches_allow()` public methods |
| `src/everstaff/permissions/dynamic_checker.py` | **NEW**: `DynamicPermissionChecker` |
| `src/everstaff/permissions/chained.py` | May be removed or simplified (DynamicPermissionChecker replaces it) |
| `src/everstaff/tools/pipeline.py` | No change (pipeline structure unchanged) |
| `src/everstaff/tools/stages.py` | Update `PermissionStage` with new deps and HITL handling |
| `src/everstaff/builder/agent_builder.py` | Refactor `_build_permissions()` per new flow |
| `src/everstaff/schema/agent_spec.py` | Update `PermissionConfig` reference |
| `src/everstaff/schema/hitl.py` | Add `TOOL_PERMISSION` type, `PermissionGrantScope` |
| `src/everstaff/tools/hitl_tool.py` | May need updates for new HITL type |
| `src/everstaff/core/context.py` | No structural change (permissions field type unchanged) |
| `src/everstaff/protocols.py` | Add `AgentDefinitionWriter` protocol |
| `src/everstaff/api/sessions.py` | Update HITL resolution endpoint for `grant_scope` |
| Channel implementations | Render `tool_permission` HITL type |
| Config/YAML templates | Add commented usage examples |
| Tests | Update all permission-related tests |

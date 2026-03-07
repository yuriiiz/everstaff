# Daemon Memory Redesign — mem0 Integration

## Context

The daemon's ThinkEngine and AgentLoop previously used a multi-layer memory system (L1 working, L2 episodic, L3 semantic) via `FileMemoryStore`. The project has migrated to mem0 for long-term memory. The old `memory_dir`-backed `memory_store` has been removed from `build_memory_store()`, making L1/L2/L3 methods non-functional (`NotImplementedError`).

This design replaces the daemon's memory usage with mem0 + a lightweight structured state store.

## What Changed on Main

- `build_memory_store()` no longer accepts `memory_dir`; `FileMemoryStore` has no `memory_store` backing
- `working_load/save`, `episode_append/query`, `semantic_read/write` all raise `NotImplementedError`
- mem0 integration added: `Mem0Client`, `Mem0Provider`, `Mem0Hook`, `Mem0ExtractionStrategy`
- `MemoryConfig` replaces `memory_dir` with `vector_store`, `vector_store_path`, etc.

## Design

### 1. Storage Split

| Data | Nature | Storage |
|------|--------|---------|
| Goal breakdowns | Structured CRUD (status, progress %) | `DaemonStateStore` (JSON via FileStore) |
| Recent decisions | Ordered list, capped at 20 | `DaemonStateStore` |
| Episode history | Free-text execution records | `mem0.add()` |
| Learning insights | Free-text patterns/risks | `mem0.add()` |
| Historical context retrieval | Semantic search | `mem0.search()` |

### 2. DaemonStateStore

Persists structured daemon state per agent at `daemon/{agent_uuid}/state.json` via the abstract `FileStore` protocol (supports local / S3).

```python
class DaemonState(BaseModel):
    goals_breakdown: dict[str, GoalBreakdown] = Field(default_factory=dict)
    recent_decisions: list[dict[str, Any]] = Field(default_factory=list)

class DaemonStateStore:
    def __init__(self, store: FileStore) -> None:
        self._store = store

    def _path(self, agent_uuid: str) -> str:
        return f"daemon/{agent_uuid}/state.json"

    async def load(self, agent_uuid: str) -> DaemonState: ...
    async def save(self, agent_uuid: str, state: DaemonState) -> None: ...
```

The `FileStore` instance is built from `config.storage` with base path = parent of `config.memory.vector_store_path` (e.g., `.agent/memory/`).

### 3. ThinkEngine Changes

#### Removed tools
- `recall_semantic_detail` — replaced by `search_memory`
- `recall_recent_episodes` — replaced by `search_memory`

#### New tool: `search_memory`
```python
ToolDefinition(
    name="search_memory",
    description="Search long-term memory for relevant historical context (past episodes, patterns, insights).",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to search for"},
        },
        "required": ["query"],
    },
)
```
Calls `mem0_client.search(query, agent_id=agent_name)`.

#### Modified tools
- `break_down_goal` / `update_goal_progress` — read/write `DaemonStateStore` instead of `WorkingState.custom`
- `record_learning_insight` — calls `mem0_client.add()` instead of `semantic_write()`

#### System prompt changes

Before (manually loads all layers):
```
## Recent episodes (5): ...
## Semantic memory topics: [...]
## Goal breakdowns: ...
```

After (mem0 for retrieval, DaemonStateStore for structured):
```
## Goal breakdowns: ...              ← DaemonStateStore
## Recent decisions (last 5): ...    ← DaemonStateStore
```
Historical context is retrieved on-demand via `search_memory` tool.

#### Constructor changes
```python
class ThinkEngine:
    def __init__(
        self,
        llm_client, tracer,
        daemon_state_store: DaemonStateStore,
        mem0_client: Mem0Client | None = None,  # None when memory.enabled=False
        sessions_dir=None, session_index=None,
    ) -> None:
```
No longer receives `memory: MemoryStore`.

### 4. AgentLoop Changes

#### Reflect phase

Before:
```python
await self._memory.episode_append(agent_name, episode)
ws = await self._memory.working_load(agent_name)
ws.recent_decisions.append(...)
await self._memory.working_save(agent_name, ws)
```

After:
```python
# Store episode in mem0 (semantic, searchable)
if self._mem0_client:
    await self._mem0_client.add(
        [{"role": "assistant", "content": episode_summary}],
        agent_id=self._agent_name,
        run_id=loop_session_id,
    )

# Update structured state
state = await self._daemon_state.load(self._agent_uuid)
state.recent_decisions.append({...})
state.recent_decisions = state.recent_decisions[-20:]
await self._daemon_state.save(self._agent_uuid, state)
```

#### Constructor changes
```python
class AgentLoop:
    def __init__(
        self,
        ...,
        daemon_state_store: DaemonStateStore,
        agent_uuid: str,
        mem0_client: Mem0Client | None = None,
        ...
    ) -> None:
```
No longer receives `memory: MemoryStore`.

### 5. AgentDaemon Changes

```python
class AgentDaemon:
    def __init__(
        self,
        ...,
        daemon_state_store: DaemonStateStore,  # replaces memory: MemoryStore
        mem0_client: Mem0Client | None = None, # NEW
        ...
    ) -> None:
```

Passes `daemon_state_store` and `mem0_client` to ThinkEngine and AgentLoop.

### 6. Wiring (api/__init__.py)

```python
# Build memory FileStore for daemon state
from pathlib import Path
memory_base = str(Path(config.memory.vector_store_path).parent)
memory_file_store = build_file_store(config.storage, memory_base)

from everstaff.daemon.state_store import DaemonStateStore
daemon_state_store = DaemonStateStore(memory_file_store)

# Build Mem0Client (shared)
mem0_client = None
if config.memory.enabled:
    from everstaff.memory.mem0_client import Mem0Client
    mem0_client = Mem0Client(config.memory, config.resolve_model(config.memory.model_kind))

daemon = AgentDaemon(
    agents_dir=config.agents_dir,
    daemon_state_store=daemon_state_store,
    mem0_client=mem0_client,
    tracer=NullTracer(),
    llm_factory=_daemon_llm_factory,
    runtime_factory=_daemon_runtime_factory,
    channel_manager=cm,
    channel_registry=channel_registry,
    sessions_dir=config.sessions_dir,
    session_index=getattr(app.state, 'session_index', None),
)
```

### 7. Graceful Degradation (memory.enabled=False)

When mem0 is disabled:
- `search_memory` tool returns `"(memory not enabled)"`
- `record_learning_insight` returns `"(memory not enabled, insight not persisted)"`
- Episode data is not stored long-term (only visible in session JSON)
- Goal breakdowns and recent decisions still work (DaemonStateStore is always available)

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| State store path | `daemon/{agent_uuid}/state.json` | UUID for uniqueness, agent_name can change |
| State store backend | `FileStore` protocol | Same abstraction as sessions, supports local/S3 |
| State store base dir | Parent of `memory.vector_store_path` | Co-located with mem0 vector data |
| Episode storage | mem0 only | No more JSONL files; mem0 extracts and indexes automatically |
| Learning insights | mem0 only | Semantic search is the right retrieval pattern |
| Think tools | Replace 2 recall tools with 1 `search_memory` | Simpler, more flexible; mem0 handles relevance |
| mem0 scope | `agent_id=agent_name` | Consistent with how AgentBuilder scopes mem0 |
| mem0 disabled | Graceful no-ops | DaemonStateStore still works; only mem0 features degrade |

## Files to Change

| File | Change |
|------|--------|
| `src/everstaff/daemon/state_store.py` | NEW: DaemonStateStore + DaemonState |
| `src/everstaff/daemon/think_engine.py` | Replace memory with DaemonStateStore + Mem0Client |
| `src/everstaff/daemon/agent_loop.py` | Replace memory with DaemonStateStore + Mem0Client |
| `src/everstaff/daemon/agent_daemon.py` | Replace memory param with new stores |
| `src/everstaff/api/__init__.py` | Wire DaemonStateStore + Mem0Client |
| `tests/test_daemon/test_think_engine.py` | Update to new APIs |
| `tests/test_daemon/test_agent_loop.py` | Update to new APIs |
| `tests/test_daemon/test_agent_daemon.py` | Update to new APIs |
| `tests/test_daemon/test_state_store.py` | NEW: DaemonStateStore tests |
| `tests/test_daemon/test_goals.py` | Update to use DaemonState |
| `tests/test_daemon/test_learning_cycle.py` | Update to use mem0 mock |
| `tests/test_daemon/test_learning_integration.py` | Update to use mem0 mock |

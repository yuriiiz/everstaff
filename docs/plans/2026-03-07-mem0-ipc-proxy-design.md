# Mem0 IPC Proxy Design

## Problem

mem0 runs directly in sandbox subprocess. The faiss vector store path
(`.agent/memory/vectors`) resolves relative to the sandbox workspace, writing
data to the wrong location. Multiple sandboxes can also conflict on the same
faiss files. API keys for embedding must be threaded through SecretStore.

## Solution

Proxy all mem0 operations (`add`/`search`) over IPC to the orchestrator,
where Mem0Client runs with correct paths and `os.environ` access.

## Data Flow

```
Sandbox                              Orchestrator
───────                              ────────────
Mem0Hook.on_session_end
  → ProxyMem0Client.add()
    → IPC "mem0.add"        ──────→  IpcServerHandler
                                       → Mem0Client.add()
                                       ← results
    ← IPC response          ←──────

Mem0Provider.refresh()
  → ProxyMem0Client.search()
    → IPC "mem0.search"     ──────→  IpcServerHandler
                                       → Mem0Client.search()
                                       ← results
    ← IPC response          ←──────
```

## Components

### 1. ProxyMem0Client

New: `src/everstaff/sandbox/proxy/mem0_client.py`

Implements same `add()`/`search()` interface as `Mem0Client`, forwarding
over IPC channel.

### 2. IpcServerHandler — mem0 routes

Modified: `src/everstaff/sandbox/ipc/server_handler.py`

Add `"mem0.add"` and `"mem0.search"` routes. Handler holds a lazy-loaded
Mem0Client from the orchestrator's DefaultEnvironment.

### 3. SandboxEnvironment cleanup

Modified: `src/everstaff/sandbox/environment.py`

Replace direct Mem0Client with ProxyMem0Client. Remove
`_get_or_create_mem0_client`, `_EMBEDDER_API_KEY_MAP`, embedder key lookup.

### 4. Orchestrator wiring

Modified: `src/everstaff/sandbox/mixin.py` (or manager)

Pass Mem0Client (or environment) to IpcServerHandler so it can serve
mem0 requests.

## IPC Messages

```python
# mem0.add
request:  {"messages": [...], "user_id": "u1", "agent_id": "a1", "run_id": "s1"}
response: {"results": [...]}

# mem0.search
request:  {"query": "...", "top_k": 10, "user_id": "u1", "agent_id": "a1"}
response: [{"memory": "...", "score": 0.9}, ...]
```

## Cleanup

- Sandbox no longer needs `install_secret_bridge` for mem0 (keep for litellm LLM calls)
- Remove `_EMBEDDER_API_KEY_MAP` from sandbox environment
- Remove `embedder_api_key` plumbing from sandbox path
- Sandbox no longer imports mem0

## Scope

- New: `src/everstaff/sandbox/proxy/mem0_client.py`
- Modified: `src/everstaff/sandbox/ipc/server_handler.py`
- Modified: `src/everstaff/sandbox/environment.py`
- Modified: `src/everstaff/sandbox/mixin.py`
- Tests for ProxyMem0Client, handler routing

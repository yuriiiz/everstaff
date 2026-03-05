# Session-in-Sandbox Architecture Design (Phase 3-5)

## Goal

Move entire AgentRuntime into isolated sandbox processes. Sandbox has no direct access
to orchestrator infrastructure (FileStore, MemoryStore, Tracer, ChannelManager).
All communication goes through an abstract IPC channel with proxy adapters.

## Architecture Overview

```
Orchestrator Process                    Sandbox Process
┌────────────────────────┐             ┌──────────────────────────┐
│ ExecutorManager        │             │ AgentRuntime             │
│ IpcServer              │◄── IPC ───►│  ├─ ProxyMemoryStore     │
│  ├─ real MemoryStore   │             │  ├─ ProxyTracer          │
│  ├─ real FileTracer    │             │  ├─ ProxyFileStore       │
│  ├─ real FileStore     │             │  ├─ SecretStore (memory) │
│  └─ ChannelManager     │             │  └─ CancellationEvent    │
│ EphemeralTokenStore    │             │ IpcChannel (client)      │
└────────────────────────┘             └──────────────────────────┘
```

## Phase Restructuring

| Phase | Content | Depends On |
|-------|---------|------------|
| **Phase 3: IPC Channel + Secret Delivery** | Abstract IPC channel, UnixSocketChannel, ephemeral token auth, secret delivery | Phase 1-2 |
| **Phase 4: Proxy Adapters** | ProxyMemoryStore, ProxyTracer, ProxyFileStore, SandboxEnvironment | Phase 3 |
| **Phase 5: Full Integration** | IPC server handler, HITL routing, cancellation, sandbox entry point, ExecutorManager upgrade | Phase 3-4 |
| **Phase 6: Docker Backend** | DockerSandbox, Dockerfile, idle timeout | Phase 3-5 |

### Small addition (Phase 1-2 supplement)

`SandboxResult` gains `started_at` / `finished_at` timestamps.

---

## Phase 3: IPC Channel + Secret Delivery

### IPC Channel Abstraction

```python
class IpcChannel(ABC):
    """Abstract bidirectional IPC channel."""

    @abstractmethod
    async def connect(self, address: str) -> None: ...

    @abstractmethod
    async def send_request(self, method: str, params: dict) -> dict:
        """Send request, wait for response (JSON-RPC style)."""
        ...

    @abstractmethod
    async def send_notification(self, method: str, params: dict) -> None:
        """Fire-and-forget notification (no response expected)."""
        ...

    @abstractmethod
    def on_push(self, method: str, handler: Callable) -> None:
        """Register handler for server-pushed messages."""
        ...

    @abstractmethod
    async def close(self) -> None: ...
```

The IPC transport is **per-sandbox-backend**:
- `ProcessSandbox` → `UnixSocketChannel`
- `DockerSandbox` → `UnixSocketChannel` (via bind-mounted socket)
- Future backends → TCP, WebSocket, etc.

### Wire Protocol: JSON-RPC 2.0

**Request (client → server):**
```json
{"jsonrpc": "2.0", "method": "memory.save", "params": {...}, "id": 1}
```

**Response (server → client):**
```json
{"jsonrpc": "2.0", "result": {...}, "id": 1}
```

**Notification (fire-and-forget, no id):**
```json
{"jsonrpc": "2.0", "method": "tracer.event", "params": {...}}
```

**Server push (server → client, no id):**
```json
{"jsonrpc": "2.0", "method": "cancel", "params": {"session_id": "..."}}
```

### Secret Delivery

Integrated into IPC channel bootstrap:

1. Orchestrator generates ephemeral token (single-use, TTL-based)
2. Spawns sandbox process, passes `socket_path` + `token` via argv/stdin
3. Sandbox connects to IPC socket
4. First message: `{method: "auth", params: {token: "..."}}`
5. Server validates token (single-use + TTL check)
6. Server responds: `{result: {secrets: {KEY: VALUE, ...}}}`
7. Sandbox creates `SecretStore` from received secrets

```python
class EphemeralTokenStore:
    """Manages single-use, TTL-based tokens for sandbox authentication."""

    def create(self, session_id: str, ttl_seconds: int = 30) -> str: ...
    def validate_and_consume(self, token: str) -> str | None:
        """Returns session_id if valid, None otherwise. Single-use."""
        ...
```

### UnixSocketChannel

Newline-delimited JSON over Unix domain socket:

```python
class UnixSocketChannel(IpcChannel):
    """IPC channel over Unix domain socket."""

    async def connect(self, socket_path: str) -> None:
        self._reader, self._writer = await asyncio.open_unix_connection(socket_path)
        # Start background listener for server pushes
        self._listen_task = asyncio.create_task(self._listen_loop())

    async def send_request(self, method: str, params: dict) -> dict:
        msg_id = self._next_id()
        future = asyncio.get_event_loop().create_future()
        self._pending[msg_id] = future
        await self._send({"jsonrpc": "2.0", "method": method, "params": params, "id": msg_id})
        return await future

    async def send_notification(self, method: str, params: dict) -> None:
        await self._send({"jsonrpc": "2.0", "method": method, "params": params})

    async def _listen_loop(self):
        """Read messages from server, dispatch responses and pushes."""
        async for line in self._reader:
            msg = json.loads(line)
            if "id" in msg and msg["id"] in self._pending:
                self._pending.pop(msg["id"]).set_result(msg.get("result"))
            elif "method" in msg:
                handler = self._push_handlers.get(msg["method"])
                if handler:
                    asyncio.create_task(handler(msg.get("params", {})))
```

---

## Phase 4: Proxy Adapters

### ProxyMemoryStore

Implements `MemoryStore` protocol. All method calls serialized as IPC requests.

```python
class ProxyMemoryStore:
    def __init__(self, channel: IpcChannel): ...

    async def save(self, session_id, messages, **kwargs) -> None:
        await self._channel.send_request("memory.save", {
            "session_id": session_id,
            "messages": [m.to_dict() for m in messages],
            **kwargs,
        })

    async def load(self, session_id: str) -> list[Message]:
        data = await self._channel.send_request("memory.load", {
            "session_id": session_id,
        })
        return [Message(**m) for m in data["messages"]]

    # L1/L2/L3 memory methods: same pattern
```

### ProxyTracer

Implements `TracingBackend`. Uses fire-and-forget notifications for low latency.

```python
class ProxyTracer:
    def __init__(self, channel: IpcChannel): ...

    def on_event(self, event: TraceEvent) -> None:
        # Fire-and-forget: don't await, don't block runtime
        asyncio.create_task(
            self._channel.send_notification("tracer.event", {
                "kind": event.kind,
                "session_id": event.session_id,
                "data": event.data,
                "timestamp": event.timestamp,
                "duration_ms": event.duration_ms,
                "trace_id": event.trace_id,
                "span_id": event.span_id,
                "parent_span_id": event.parent_span_id,
            })
        )
```

### ProxyFileStore

Implements `FileStore` protocol. All operations forwarded via IPC.

```python
class ProxyFileStore:
    def __init__(self, channel: IpcChannel): ...

    async def read(self, path: str) -> bytes: ...
    async def write(self, path: str, data: bytes) -> None: ...
    async def exists(self, path: str) -> bool: ...
    async def delete(self, path: str) -> None: ...
    async def list(self, prefix: str) -> list[str]: ...
```

### SandboxEnvironment

New `RuntimeEnvironment` subclass for sandbox processes:

```python
class SandboxEnvironment(RuntimeEnvironment):
    def __init__(self, channel: IpcChannel, secret_store: SecretStore,
                 workspace_dir: Path, config: FrameworkConfig | None = None):
        super().__init__(config=config)
        self._channel = channel
        self._secret_store = secret_store
        self._workspace_dir = workspace_dir

    def build_memory_store(self, max_tokens=None) -> MemoryStore:
        return ProxyMemoryStore(self._channel)

    def build_tracer(self, session_id="") -> TracingBackend:
        return ProxyTracer(self._channel)

    def build_file_store(self) -> FileStore:
        return ProxyFileStore(self._channel)

    def build_llm_client(self, model: str, **kwargs) -> LLMClient:
        # LLM calls execute directly in sandbox
        # API keys come from SecretStore → set in env or pass to client
        from everstaff.llm.litellm_client import LiteLLMClient
        return LiteLLMClient(model=model, **kwargs)

    def working_dir(self, session_id: str) -> Path:
        return self._workspace_dir

    @property
    def secret_store(self) -> SecretStore:
        return self._secret_store
```

---

## Phase 5: Full Integration

### IPC Server (Orchestrator Side)

```python
class IpcServer:
    """Runs in orchestrator, handles sandbox IPC connections."""

    def __init__(self, memory_store, tracer, file_store, channel_manager): ...

    async def start(self, socket_path: str) -> None:
        self._server = await asyncio.start_unix_server(
            self._handle_connection, socket_path
        )

    async def _handle_connection(self, reader, writer):
        """Handle one sandbox connection."""
        async for line in reader:
            msg = json.loads(line)
            method = msg.get("method")
            params = msg.get("params", {})
            msg_id = msg.get("id")

            if method == "auth":
                result = self._handle_auth(params)
            elif method == "memory.save":
                result = await self._handle_memory_save(params)
            elif method == "memory.load":
                result = await self._handle_memory_load(params)
            elif method == "tracer.event":
                self._handle_tracer_event(params)
                continue  # notification, no response
            elif method == "hitl.request":
                result = await self._handle_hitl(params)
            elif method.startswith("file."):
                result = await self._handle_file_op(method, params)
            else:
                result = {"error": f"Unknown method: {method}"}

            if msg_id is not None:
                response = {"jsonrpc": "2.0", "result": result, "id": msg_id}
                writer.write(json.dumps(response).encode() + b"\n")
                await writer.drain()
```

### HITL Routing

When sandbox runtime raises `HumanApprovalRequired`:
1. Runtime saves session via `ProxyMemoryStore.save(status="waiting_for_human")`
2. IPC server handler detects `status=waiting_for_human` with hitl_requests
3. IPC server calls `channel_manager.broadcast()` for daemon sessions
4. Web sessions: session.json is already updated via the save, clients poll normally
5. HITL resolution: orchestrator receives resolution, pushes to sandbox via IPC
6. Sandbox resumes runtime

No new IPC method needed for HITL broadcast — it piggybacks on `memory.save`.
Orchestrator detects HITL from the saved status and hitl_requests fields.

HITL resolution push:
```json
{"jsonrpc": "2.0", "method": "hitl.resolution", "params": {
    "hitl_id": "...",
    "decision": "approved",
    "comment": "..."
}}
```

### Cancellation

**Stop flow:**
1. API handler calls `ExecutorManager.destroy(session_id)`
2. `destroy()` closes IPC channel → sandbox ProxyMemoryStore writes fail immediately
3. `destroy()` waits for sandbox process to exit
4. Sets session status to "cancelled" in MemoryStore

**Race condition prevention:**
- `destroy()` is synchronous — blocks until process exits
- IPC channel closure prevents stale writes
- Resume requires sandbox to be fully stopped

```python
class ExecutorManager:
    async def destroy(self, session_id: str) -> None:
        executor = self._executors.pop(session_id, None)
        if executor is None:
            return
        await executor.stop()  # closes IPC + kills process + waits for exit
```

### Sandbox Entry Point

```python
# src/everstaff/sandbox/entry.py
async def sandbox_main(socket_path: str, token: str, session_id: str,
                       agent_spec_json: str, user_input: str | None):
    """Entry point for sandbox process."""
    # 1. Connect and authenticate
    channel = UnixSocketChannel()
    await channel.connect(socket_path)
    auth_result = await channel.send_request("auth", {"token": token})
    secret_store = SecretStore(auth_result["secrets"])

    # 2. Build environment
    workspace = Path("/work")  # or configurable
    env = SandboxEnvironment(
        channel=channel,
        secret_store=secret_store,
        workspace_dir=workspace,
    )

    # 3. Build and run AgentRuntime
    spec = AgentSpec.model_validate_json(agent_spec_json)
    builder = AgentBuilder(spec, env, session_id=session_id)
    runtime, ctx = await builder.build()

    # 4. Register cancel handler
    channel.on_push("cancel", lambda params: ctx.cancellation.cancel())

    # 5. Register HITL resolution handler
    channel.on_push("hitl.resolution", lambda params: ...)

    # 6. Run runtime
    async for event in runtime.run_stream(user_input):
        pass  # All saves/traces go through proxies automatically
```

### Subagent Delegation

Child agents run in the **same sandbox** as the parent. No IPC needed for delegation.
The existing `delegate_task_to_subagent` tool works as-is because:
- It creates a new AgentBuilder + AgentRuntime in-process
- All proxies (ProxyMemoryStore, ProxyTracer) are shared
- Child session saves go through the same IPC channel

---

## Phase 6: Docker Backend

### DockerSandbox

```python
class DockerSandbox(SandboxExecutor):
    """Docker container sandbox."""

    async def start(self, session_id: str, workspace_dir: Path) -> None:
        # 1. Create IPC socket in temp dir
        # 2. Start IPC server
        # 3. Generate ephemeral token
        # 4. Run container:
        #    - Mount workspace: -v workspace_dir:/work
        #    - Mount IPC socket: -v /tmp/ipc-xxx.sock:/ipc.sock
        #    - Pass token + socket path via env
        #    - Resource limits from SandboxDockerConfig
        #    - Run: python -m everstaff.sandbox.entry
        pass
```

### Workspace Strategy by Backend

| Backend | Workspace | Persistence |
|---------|-----------|-------------|
| ProcessSandbox | Local directory on host | Direct access |
| DockerSandbox | Bind mount from host | Survives container restart |
| CloudSandbox (future) | Cloud volume or sync | Backend-specific |

---

## SandboxResult Timestamp Addition

```python
class SandboxResult(BaseModel):
    success: bool
    output: str = ""
    exit_code: int = 0
    error: str = ""
    started_at: float | None = None   # time.monotonic() when command started
    finished_at: float | None = None  # time.monotonic() when command finished
```

---

## Key Design Decisions

1. **IPC transport is per-sandbox-backend** — abstracted behind `IpcChannel` ABC
2. **Proxy adapters** — implement same Protocol interfaces, AgentRuntime zero changes
3. **Tracing: full forwarding** — fire-and-forget notifications, no batching
4. **HITL: piggyback on memory.save** — orchestrator detects hitl status from save
5. **Cancel: destroy() is synchronous** — close IPC → wait for exit → set cancelled
6. **Subagent: same sandbox** — no cross-sandbox delegation needed
7. **Workspace: sandbox backend responsibility** — local path, bind mount, or cloud volume
8. **Secret delivery: first IPC message** — auth with ephemeral token, receive secrets

## Files to Create/Modify

### New Files
- `src/everstaff/sandbox/ipc/__init__.py`
- `src/everstaff/sandbox/ipc/channel.py` — IpcChannel ABC
- `src/everstaff/sandbox/ipc/unix_socket.py` — UnixSocketChannel
- `src/everstaff/sandbox/ipc/server.py` — IpcServer
- `src/everstaff/sandbox/ipc/protocol.py` — JSON-RPC message models
- `src/everstaff/sandbox/proxy/memory_store.py` — ProxyMemoryStore
- `src/everstaff/sandbox/proxy/tracer.py` — ProxyTracer
- `src/everstaff/sandbox/proxy/file_store.py` — ProxyFileStore
- `src/everstaff/sandbox/environment.py` — SandboxEnvironment
- `src/everstaff/sandbox/entry.py` — sandbox process entry point
- `src/everstaff/sandbox/token_store.py` — EphemeralTokenStore

### Modified Files
- `src/everstaff/sandbox/models.py` — add started_at/finished_at to SandboxResult
- `src/everstaff/sandbox/executor.py` — add workspace_dir to start()
- `src/everstaff/sandbox/process_sandbox.py` — integrate IPC server + token auth
- `src/everstaff/sandbox/manager.py` — synchronous destroy, cancel support

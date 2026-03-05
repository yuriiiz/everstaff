# Sandbox Isolation Design

## Problem

Sessions run as async tasks in the same Python process as the service. All subprocesses (Bash, MCP) inherit the parent process environment. This means any agent can execute `printenv` and read service-level secrets (API keys, database passwords, etc.). Agents can also be manipulated via prompt injection to open TCP tunnels and exfiltrate data.

## Threat Model

1. **Environment variable leakage**: Bash/MCP subprocesses inherit all parent env vars, exposing service secrets
2. **TCP tunnel exfiltration**: Agent induced by prompt injection to open reverse tunnels (ssh -R, ngrok, socat)
3. **Untrusted agent / sandbox escape**: Agent code is not trusted; need hard isolation boundaries

## Design: Orchestrator + Sandbox Session

### Architecture Overview

```
┌─ Orchestrator (main process) ─────────────────────┐
│                                                    │
│  Session lifecycle management                      │
│  Sandbox creation/recycle (ExecutorManager)         │
│  HITL event routing (ChannelManager)               │
│  Subagent/DAG scheduling                           │
│  Secret Broker (TLS bootstrap)                     │
│  API layer (FastAPI)                               │
│  Holds all .env secrets                            │
│                                                    │
│  *** No agent code runs here ***                   │
└──────────────────┬─────────────────────────────────┘
                   │ IPC (TLS over Unix Socket)
     ┌─────────────┼─────────────┐
     ▼             ▼             ▼
┌─────────┐  ┌─────────┐  ┌─────────┐
│Sandbox A│  │Sandbox B│  │Sandbox C│
│         │  │         │  │         │
│ Runtime │  │ Runtime │  │ Runtime │
│ + Tools │  │ + Tools │  │ + Tools │
│ + MCP   │  │ + MCP   │  │ + MCP   │
│         │  │         │  │         │
│SecretSt.│  │SecretSt.│  │SecretSt.│
│(memory) │  │(memory) │  │(memory) │
└─────────┘  └─────────┘  └─────────┘
```

The entire AgentRuntime (LLM conversation loop + tool execution) runs inside the sandbox. The Orchestrator only manages lifecycle, routing, and scheduling.

### Security Model: Zero-Value Sandbox

The security principle is not to restrict network access (agents need it), but to ensure **the execution environment has nothing valuable to steal**.

| Layer | What it can see | Notes |
|-------|----------------|-------|
| Orchestrator process | All .env secrets | Only runs orchestration logic, no agent code |
| Sandbox (Python memory) | All .env via SecretStore | In-memory only, not in `os.environ`, not on disk |
| MCP subprocess | Only its declared `spec.env` | Injected from SecretStore at startup |
| Bash subprocess | **Empty environment** | `printenv` / `env` returns nothing |
| Workspace filesystem | Only session workspace | No secret files present |

Even if an agent opens a TCP tunnel from within a Bash command, the Bash process has no secrets in its environment and no secret files on disk.

### Secret Delivery: Ephemeral Token + TLS Bootstrap

```
Orchestrator
  │
  1. Generate ephemeral token (one-time, 30s TTL)
  2. Pass token to sandbox via stdin pipe (invisible to ps, not in env)
  │
  ▼
Sandbox starts
  3. Uses token to initiate mTLS handshake with Orchestrator
  4. Encrypted P2P channel established
  │
  ▼
  5. Orchestrator pushes all .env secrets over encrypted channel
  6. Sandbox stores in SecretStore (in-process memory, no disk, no env vars)
  │
  ▼
  7. Token immediately invalidated (single use)
```

Key properties:
- Token passed via stdin pipe: invisible to `ps`, not in environment variables
- Token is one-time use with 30s expiry
- Secrets transmitted over TLS, stored only in Python memory
- Bash subprocesses get clean environment (no secrets)
- MCP servers receive only their declared `spec.env` from SecretStore

### What Runs Where

**Orchestrator (main process):**
- Session lifecycle management (create, pause, resume, destroy)
- Sandbox creation and recycling
- HITL event routing to external channels
- Subagent and DAG workflow scheduling
- Framework-level write operations (`create_agent`, `create_skill`, `system_reconcile`)
- API endpoints (FastAPI)

**Sandbox (isolated environment):**
- AgentRuntime (LLM conversation loop)
- DynamicPermissionChecker
- Bash command execution (clean env)
- MCP server startup and tool calls
- Custom native tools (Python functions from tools_dirs)
- Skill script execution
- File read/write (workspace only)

**IPC required for (sandbox → orchestrator):**
- HITL events (human approval needed)
- `delegate_task_to_subagent` (request child sandbox creation)
- `create_agent` / `create_skill` (framework-level writes outside workspace)
- Session state sync (completion, failure, cancellation)

### Subagent and DAG Support

Each sub-agent runs in its own independent sandbox. The Orchestrator coordinates:

```
Orchestrator (lightweight scheduler)
│
├── Sandbox_A (parent agent)
│   └── delegate_task_to_subagent
│       → IPC → Orchestrator: "create child sandbox"
│
├── Sandbox_B (child agent, fully independent)
│   └── completes → IPC → Orchestrator → IPC → Sandbox_A
│
│ DAG example: A → B, A → C, B+C → D
│
│ t0: Create Sandbox_A → runs independently
│ t1: A completes → create Sandbox_B & Sandbox_C in parallel
│ t2: B & C complete → create Sandbox_D
│ t3: D completes → workflow done
```

Benefits:
- Runtime load distributed across sandboxes (no single bottleneck)
- Each sandbox fully independent (different agents can't interfere)
- Sandboxes can potentially run on different machines (future scalability)

### Sandbox Backends

Abstract interface allows multiple implementations:

```python
class SandboxExecutor(ABC):
    """Sandbox executor abstract base class."""

    @abstractmethod
    async def start(self, session_id: str) -> None:
        """Start sandbox, complete TLS bootstrap and secret injection."""

    @abstractmethod
    async def send_command(self, command: SandboxCommand) -> SandboxResult:
        """Send a command to the sandbox runtime via IPC."""

    @abstractmethod
    async def stop(self) -> None:
        """Destroy sandbox, cleanup resources."""

    @property
    @abstractmethod
    def is_alive(self) -> bool:
        """Whether the sandbox is still running."""
```

**ProcessSandbox** (development, macOS/Linux):
- Subprocess with clean environment
- Path restriction to workspace directory (realpath escape check)
- SecretStore in child process memory
- IPC via Unix socket + TLS

**DockerSandbox** (production, Linux):
- Lightweight container per session
- Only workspace directory mounted (bind mount)
- Secrets via TLS bootstrap into container process memory
- Container network unrestricted (agents need internet)
- Optional: gVisor runtime for stronger isolation

**Custom backends**: Implement `SandboxExecutor` interface for gVisor, Firecracker, remote execution, etc.

### Executor Lifecycle

```
Session created → no sandbox yet (lazy)
First tool call → create sandbox (TLS bootstrap, inject secrets)
Session active  → sandbox running, handling tool calls
Session idle    → idle_timeout countdown starts
Idle expired    → sandbox destroyed, resources freed
Session resumes → new sandbox created (workspace persists on disk)
Session ends    → sandbox destroyed
```

Configuration:
```yaml
execution:
  sandbox:
    type: auto  # auto | process | docker | custom
    idle_timeout: 300  # seconds
    token_ttl: 30  # ephemeral token validity

    docker:
      image: "everstaff/executor:latest"
      memory_limit: "512m"
      cpu_limit: 1.0

    extra_mounts:  # optional read-only mounts
      - source: /data/shared_models
        target: /mnt/models
        readonly: true
```

### Workspace Interaction

Workspace is the shared data layer between Orchestrator and Sandbox:

```
Host: .agent/sessions/{session_id}/workspace/
│
├── Orchestrator: read-only (view results, logs)
├── Sandbox: read-write (tool execution working directory)
│
│ ProcessSandbox: direct path access (with escape check)
│ DockerSandbox:  bind mount (-v workspace:/work)
```

### Integration Points

Current Bash tool flow:
```
runtime → bash_tool.execute() → asyncio.create_subprocess_shell()
```

New flow (inside sandbox):
```
sandbox runtime → bash_tool.execute()
  → create_subprocess_shell(env={})  # clean environment
  → if tool needs specific secret: inject from SecretStore
```

Current MCP flow:
```
runtime → mcp_client.connect(spec) → StdioServerParameters(env=spec.env)
```

New flow (inside sandbox):
```
sandbox runtime → mcp_client.connect(spec)
  → resolve spec.env values from SecretStore (memory)
  → StdioServerParameters(env=resolved_env)
```

## Decisions

- **Whole session in sandbox** (not just tools) — reduces IPC overhead, enables distributed scaling
- **All .env secrets** transmitted to sandbox SecretStore — agent needs are dynamic, can't predict
- **No network restriction** — agents need internet; security comes from zero-value environment
- **Server-side sandbox config** — not in agent YAML (agents are untrusted)
- **Lazy sandbox creation** — only when first tool call happens
- **Idle timeout recycling** — sandbox destroyed after inactivity, recreated on demand

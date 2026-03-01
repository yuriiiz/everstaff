# Everstaff

**AI agents that know when to act and when to ask — autonomous by default, human-supervised when it counts.**

Everstaff is an open-source platform for running AI agents that work around the clock. Agents operate autonomously, but pause and request human approval at critical decisions. Every step is observable, every action is permissioned.

---

## Features

### Core Runtime
- **Multi-LLM support** — OpenAI, Anthropic, Gemini, and 100+ providers via LiteLLM
- **Streaming** — real-time WebSocket streaming with a built-in web UI
- **Session persistence** — resume any session from where it left off
- **Tool permissions** — fine-grained allow/deny rules with wildcard matching

### Human-in-the-Loop (HITL)
- Agents pause mid-run and request human approval before critical actions
- Approve, reject, or comment directly from the web UI
- Configurable: block on every tool call, only on request, or never
- Async — agents queue HITL requests and wait without blocking other work

### Multi-Agent
- Delegate subtasks to specialized child agents
- DAG-based workflow engine with parallel execution and automatic replanning
- Child agent results flow back to the parent agent transparently

### Autonomous Daemon
- Schedule agents on cron, webhooks, or custom events
- Agents run unattended and escalate to humans when needed
- Per-trigger HITL channels — each trigger gets its own approval queue

### Extensibility
- **Skills** — composable instruction modules agents load on demand
- **Tools** — Python functions exposed to agents with typed schemas
- **Knowledge base** — attach document directories for context injection
- **MCP servers** — connect any Model Context Protocol server

### Production Ready
- OIDC authentication with email whitelist
- OpenTelemetry and Langfuse tracing
- S3 or local storage for session data
- Docker image included

---

## Quick Start

### Install

```bash
pip install everstaff
```

### Run the server

```bash
everstaff serve
```

Open [http://localhost:8000](http://localhost:8000) — the web UI is bundled.

### Docker

```bash
docker run -p 8000:8000 \
  -v $(pwd)/.agent:/app/.agent \
  -e ANTHROPIC_API_KEY=sk-... \
  ghcr.io/your-org/everstaff
```

---

## How It Works

Agents are defined in a config file. Drop one in your `.agent/agents/` directory and it appears in the UI immediately.

```yaml
agent_name: Code Reviewer
instructions: |
  Review pull requests for bugs, security issues, and style violations.
  When you find a critical issue, request human approval before proceeding.

tools: [Bash, Read, Glob, Grep]

hitl_mode: on_request   # pause and ask when uncertain

autonomy:
  triggers:
    - type: webhook
      path: /hooks/github
```

---

## Documentation

- [Getting Started](docs/getting-started.md)
- [Architecture](docs/architecture.md)
- [API Reference](docs/api-reference.md)
- [Permissions](docs/module-permissions.md)
- [Skills](docs/module-skills.md)
- [Workflow Engine](docs/module-workflow.md)
- [Tracing](docs/module-tracing.md)

---

## Development

```bash
# Install dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Start dev server (API + frontend separately)
uvicorn everstaff.server:app --reload
cd web && npm install && npm run dev
```

---

## License

MIT

# Everstaff Usage Guide

## Installation

```bash
pip install everstaff-0.1.7-py3-none-any.whl

# With optional extras:
pip install "everstaff-0.1.7-py3-none-any.whl[lark]"    # Lark channel support
pip install "everstaff-0.1.7-py3-none-any.whl[otel]"    # OpenTelemetry tracing
pip install "everstaff-0.1.7-py3-none-any.whl[all]"     # Everything
```

---

## Project Layout

```
my-project/
├── config/
│   └── config.yaml         # Framework config (model mappings, skills dirs, storage, tracers, etc.)
├── agents/
│   └── my_agent.yaml       # Agent definition
├── skills/                 # Custom skills (optional)
│   └── my-skill/
│       └── SKILL.md
├── tools/                  # Custom tools (optional)
│   └── my_tool.py
├── knowledges/             # Knowledge base files (optional)
│   └── docs/
│       └── README.md
└── main.py                 # Entry point (if running as a server)
```

---

## Config Files

### `config/config.yaml`

All framework settings in a single file. The framework uses three named model tiers: `smart`, `fast`, `reasoning`.

```yaml
agents_dir: "./agents"
sessions_dir: ".agent/sessions"

# Your custom skills/tools are appended AFTER builtin ones
skills_dirs:
  - "./skills"
tools_dirs:
  - "./tools"

model_mappings:
  smart:
    model_id: "claude-sonnet-4-6"    # Any LiteLLM model string
    max_tokens: 16000
    temperature: 0.7
    supports_tools: true
    cost_per_input_token: 0.000003
    cost_per_output_token: 0.000015
  fast:
    model_id: "claude-haiku-4-5-20251001"
    max_tokens: 8000
    temperature: 0.5
    supports_tools: true
    cost_per_input_token: 0.00000025
    cost_per_output_token: 0.00000125
  reasoning:
    model_id: "claude-opus-4-6"
    max_tokens: 32000
    temperature: 1.0
    supports_tools: true
    cost_per_input_token: 0.000015
    cost_per_output_token: 0.000075

storage:
  type: local
  # type: s3
  # s3_bucket: "my-bucket"
  # s3_prefix: "sessions"
  # s3_region: "us-east-1"

tracers:
  - type: file      # writes to .agent/sessions/<session_id>/trace.jsonl
  - type: console   # prints spans to stdout

# Lark channel (optional):
# channels:
#   lark-ws-main:
#     type: lark_ws
#     app_id: "cli_xxx"
#     app_secret: "xxx"
#     chat_id: "oc_xxx"
#     bot_name: "MyAgent"
#     feishu_tools: ["im", "docs", "calendar", "tasks", "minutes"]
#     auto_allow_tools: ["*"]
```

---

## Agent Definition

### `agents/my_agent.yaml`

```yaml
uuid: a1b2c3d4-0000-0000-0000-000000000001   # optional, for tracking
agent_name: My Agent
description: A helpful assistant that can read files and run commands.
version: 1.0.0

adviced_model_kind: smart   # smart | fast | reasoning

instructions: |
  You are a helpful assistant. You can read files, run commands,
  and help users with technical tasks. Always be concise and accurate.

# Built-in tools from everstaff.builtin_tools:
#   Bash, Read, Write, Edit, Glob, Grep
tools:
  - Bash
  - Read
  - Write
  - Edit
  - Glob
  - Grep

# Skills to load (builtin skills need no extra config):
skills:
  - find-skills

# Knowledge base (optional):
knowledge_base:
  - type: local_dir
    path: ./knowledges/docs

# MCP servers (optional):
mcp_servers:
  - name: my-server
    command: python
    args: [./tools/mcp_server.py]
    transport: stdio

# Sub-agents (optional):
sub_agents:
  researcher:
    description: Searches and summarizes information.
    instructions: You are a research assistant. Find accurate information.
    adviced_model_kind: fast
    tools: [Bash]
    skills: []
    knowledge_base: []
    mcp_servers: []
    max_turns: 10

# Human-in-the-loop: on_request | never
hitl_mode: on_request

# Permission rules for tools:
permissions:
  allow: []     # empty = allow all
  deny: []

# Workflow / multi-agent coordination (optional):
# workflow:
#   enable: true
#   max_replans: 2
#   max_parallel: 3
```

---

## Running

### CLI — interactive

```bash
# Run agent interactively (reads config/ automatically)
agent run agents/my_agent.yaml --config config/

# Single-shot mode
agent run agents/my_agent.yaml --config config/ --single "Summarize README.md"

# Resume a previous session
agent run agents/my_agent.yaml --config config/ --resume <session-id>

# Override the model
agent run agents/my_agent.yaml --config config/ --model-override "gpt-4o"
```

### CLI — utilities

```bash
# List discovered skills
agent skills list --config config/

# List saved sessions
agent sessions list --config config/

# Show session history
agent sessions show <session-id> --config config/

# Show agent info
agent info agents/my_agent.yaml --config config/
```

### Server (FastAPI)

Create a `main.py`:

```python
import everstaff
import uvicorn

app = everstaff.create_app(config_dir="./config")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

```bash
python main.py
# or
uvicorn main:app --reload
```

The server exposes a REST + WebSocket API. Key endpoints:

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/agents` | List available agent definitions |
| `POST` | `/sessions` | Start a new session |
| `POST` | `/sessions/{id}/chat` | Send a message |
| `GET` | `/sessions/{id}/stream` | Stream responses (SSE) |
| `GET` | `/sessions` | List sessions |
| `POST` | `/hitl/{hitl_id}/resolve` | Resolve a human-in-the-loop request |
| `GET` | `/skills` | List loaded skills |

---

## Custom Skills

A skill is a directory with a `SKILL.md` file:

```
skills/
└── my-skill/
    └── SKILL.md
```

`SKILL.md` format:

```markdown
---
name: my-skill
description: One-line description shown to the agent so it knows when to use this skill.
---

# My Skill

Instructions that get injected into the agent's context when this skill is invoked.
```

Reference the skill in your agent yaml:

```yaml
skills:
  - my-skill
```

---

## Environment Variables

Override model IDs at runtime without changing config files:

```bash
AGENT_MODEL_SMART=gpt-4o agent run agents/my_agent.yaml --config config/
AGENT_MODEL_FAST=gpt-4o-mini agent run agents/my_agent.yaml --config config/
```

---

## Minimal Example

The smallest possible working project:

```
hello/
├── config/
│   └── config.yaml
└── agents/
    └── hello.yaml
```

`config/config.yaml`:
```yaml
agents_dir: ./agents
sessions_dir: .agent/sessions
tracers:
  - type: console

model_mappings:
  smart:
    model_id: "gpt-4o-mini"
    max_tokens: 4096
    temperature: 0.7
    supports_tools: true
```

`agents/hello.yaml`:
```yaml
agent_name: Hello
description: A simple hello-world agent.
adviced_model_kind: smart
instructions: You are a friendly assistant. Keep responses short.
tools: []
skills: []
```

```bash
cd hello
agent run agents/hello.yaml --config config/
```

"""Project scaffolding for `agent init`."""
from __future__ import annotations

from pathlib import Path

TEMPLATES: dict[str, str] = {
    "pyproject.toml": """\
[project]
name = "{project_name}"
version = "0.1.0"
description = ""
requires-python = ">=3.11"
dependencies = [
    "everstaff>=0.1.7",
    "python-dotenv>=1.0.0",
]
""",
    ".agent/config.yaml": """\
# =============================================================================
# Everstaff Framework Configuration
# All available keys listed. Commented-out sections are optional/advanced.
# Supports ${{ENV_VAR}} substitution in string values.
# =============================================================================

# ---------------------------------------------------------------------------
# Directories
# ---------------------------------------------------------------------------
agents_dir: "./agents"

skills_dirs:
  - "./skills"
  # - ".agent/skills"

tools_dirs:
  - "./tools"

mcp_templates_dirs:
  - ".agent/mcp_templates"

sessions_dir: ".agent/sessions"

# ---------------------------------------------------------------------------
# Project Context — files injected into agent system prompts
# ---------------------------------------------------------------------------
context:
  project_context_dirs:
    - ".agent/project"

# ---------------------------------------------------------------------------
# Model Mappings
# Maps logical model kinds (smart / fast / reasoning) to LiteLLM model strings.
# Env override: AGENT_MODEL_SMART=xxx, AGENT_MODEL_FAST=xxx, etc.
# LLM providers (via litellm): openai, anthropic, minimax, groq, together,
#   deepseek, ollama, aws_bedrock, azure_openai, gemini, xai, etc.
# ---------------------------------------------------------------------------
model_mappings:
  smart:
    model_id: "anthropic/claude-sonnet-4-20250514"
    max_tokens: 8192
    temperature: 0.7
    supports_tools: true
  fast:
    model_id: "anthropic/claude-haiku-4-5-20251001"
    max_tokens: 4096
    temperature: 0.5
    supports_tools: true
  reasoning:
    model_id: "anthropic/claude-opus-4-6"
    max_tokens: 16384
    temperature: 1.0
    supports_tools: true

  # Embedding model (used by mem0 memory).
  # Embedding providers (via mem0): openai (default), ollama, huggingface,
  #   azure_openai, gemini, vertexai, together, aws_bedrock, fastembed
  # Examples: text-embedding-3-small, huggingface/all-MiniLM-L6-v2,
  #           ollama/nomic-embed-text
  embedding:
    model_id: "text-embedding-3-small"

# ---------------------------------------------------------------------------
# Storage — session persistence backend
# ---------------------------------------------------------------------------
storage:
  type: "local"                    # "local" | "s3"
  # s3_bucket: ""
  # s3_prefix: "sessions"
  # s3_region: "us-east-1"
  # s3_endpoint_url: null          # custom S3-compatible endpoint
  # s3_access_key: null            # falls back to boto3 credential chain
  # s3_secret_key: null

# ---------------------------------------------------------------------------
# Tracers — trace event recording backends
# ---------------------------------------------------------------------------
tracers:
  - type: console                  # "file" | "console" | "otlp"
  - type: file
  # - type: otlp

# ---------------------------------------------------------------------------
# Web UI
# ---------------------------------------------------------------------------
web:
  enabled: true

# ---------------------------------------------------------------------------
# Daemon — autonomous agent background execution
# ---------------------------------------------------------------------------
daemon:
  enabled: true
  watch_interval: 10               # seconds between polling for scheduled tasks
  graceful_stop_timeout: 300       # seconds to wait for graceful shutdown
  max_concurrent_loops: 10         # max parallel daemon loop executions

# ---------------------------------------------------------------------------
# Permissions — tool call allow/deny rules
# Patterns: "ToolName", "ToolName(*)", "ToolName(ls *)", "ToolName(command:ls *)"
# Tools not in the allow list automatically trigger HITL approval.
# ---------------------------------------------------------------------------
# permissions:
#   allow: []                      # empty = all tools need HITL
#   deny: []                       # deny takes precedence over allow

# ---------------------------------------------------------------------------
# Channels — HITL (Human-in-the-Loop) communication channels
# Keyed by channel name. Each entry uses "type" to discriminate.
# Supported types: "lark_ws", "lark", "webhook"
# ---------------------------------------------------------------------------
# channels:
#   lark-ws-main:
#     type: "lark_ws"
#     app_id: "${{LARK_APP_ID}}"
#     app_secret: "${{LARK_APP_SECRET}}"
#     chat_id: "oc_xxxxx"           # default chat_id (can be overridden per agent)
#     bot_name: "Agent"
#     domain: "feishu"              # "feishu" | "lark"
#     web_url: "http://localhost:5173"
#     allowed_emails: []            # email allowlist (empty = allow all)
#     feishu_tools:                 # Feishu user-identity tool categories
#       - "im"
#       - "docs"
#       - "calendar"
#       - "tasks"
#       - "minutes"
#       - "bitable"
#     auto_allow_tools: ["*"]      # ["*"] = allow all, or list specific tool names
#     offline_access: true          # auto-append "offline_access" scope for refresh tokens
#     base_scopes:                  # override default OAuth scopes (null = built-in defaults)
#       - "im:message"
#       - "im:message:readonly"
#       - "im:chat:read"
#       - "calendar:calendar:read"
#       - "task:task:readonly"
#       - "docx:document:readonly"
#       - "wiki:wiki:readonly"
#       - "minutes:minutes"
#       - "search:message"
#
#   lark-main:
#     type: "lark"
#     app_id: "${{LARK_APP_ID}}"
#     app_secret: "${{LARK_APP_SECRET}}"
#     verification_token: "${{LARK_VERIFICATION_TOKEN}}"
#     chat_id: "oc_xxxxx"
#     bot_name: "Agent"
#     domain: "feishu"
#
#   webhook-main:
#     type: "webhook"
#     url: "https://example.com/webhooks/hitl"
#     headers:
#       Authorization: "Bearer ${{WEBHOOK_TOKEN}}"

# ---------------------------------------------------------------------------
# Memory — long-term memory powered by mem0
# ---------------------------------------------------------------------------
# memory:
#   enabled: true
#   llm_model_kind: fast             # model_mappings key for extraction LLM
#   embedding_model_kind: embedding  # model_mappings key for embedding model
#   vector_store: faiss              # faiss | chroma | qdrant
#   vector_store_path: ".agent/memory/vectors"
#   search_top_k: 10
#   search_threshold: 0.3

# ---------------------------------------------------------------------------
# Sandbox — isolated tool execution environment
# ---------------------------------------------------------------------------
# sandbox:
#   enabled: true
#   type: "auto"                     # "auto" | "process" | "docker"
#   idle_timeout: 300                # seconds before idle executor is stopped
#   token_ttl: 30                    # seconds for one-time auth tokens
#   docker:
#     image: "everstaff/executor:latest"
#     memory_limit: "512m"
#     cpu_limit: 1.0
#   extra_mounts:
#     - source: "/host/path"
#       target: "/container/path"
#       readonly: true

# ---------------------------------------------------------------------------
# Auth — authentication middleware
# Provider types: "oidc_code", "oidc", "jwt", "proxy"
# ---------------------------------------------------------------------------
# auth:
#   enabled: true
#   public_routes:
#     - "/api/ping"
#     - "/docs"
#     - "/openapi.json"
#     - "/redoc"
#   allowed_emails: []               # empty = allow all authenticated users
#   providers:
#     # --- OIDC Authorization Code Flow (browser login) ---
#     - type: "oidc_code"
#       issuer: "https://accounts.google.com"
#       client_id: "${{OIDC_CLIENT_ID}}"
#       client_secret: "${{OIDC_CLIENT_SECRET}}"
#       redirect_uri: "http://localhost:5173/auth/callback"
#       scopes: ["openid", "email", "profile"]
#       cookie_secret: "${{COOKIE_SECRET}}"
#       cookie_name: "agent_session"
#       cookie_max_age: 86400
#
#     # --- OIDC (Bearer token validation) ---
#     # - type: "oidc"
#     #   issuer: "https://accounts.google.com"
#     #   audience: null
#     #   claims_mapping:
#     #     user_id: "sub"
#     #     name: "name"
#     #     email: "email"
#
#     # --- JWT (custom token) ---
#     # - type: "jwt"
#     #   header: "X-Auth-Token"
#     #   secret: "${{JWT_SECRET}}"   # HS256
#     #   algorithm: "HS256"
#     #   # jwks_url: null            # for RS256
#     #   claims_mapping:
#     #     user_id: "sub"
#     #     name: "name"
#     #     email: "email"
#
#     # --- Proxy (trusted reverse proxy) ---
#     # - type: "proxy"
#     #   headers:
#     #     user_id: "X-Forwarded-User"
#     #     email: "X-Forwarded-Email"
#     #     name: "X-Forwarded-Name"
#     #   trusted_cidrs:
#     #     - "10.0.0.0/8"
""",
    "main.py": """\
\"\"\"Entry point for {project_name}.

Usage:
    uv run python main.py
    uv run python main.py --host 0.0.0.0 --port 8000 --reload
\"\"\"

import os
import argparse

from dotenv import load_dotenv


def pre_start():
    \"\"\"Custom actions to run before the server starts.

    Add your own initialization logic here, e.g.:
    - Register custom tools / skills programmatically
    - Set up external connections
    - Validate environment variables
    - Seed data
    \"\"\"
    pass


def main():
    load_dotenv()

    parser = argparse.ArgumentParser(description="{project_name}")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")
    args = parser.parse_args()

    # --- Custom pre-start hook ---
    pre_start()

    # --- Configure logging ---
    from everstaff.utils.logging import setup_logging

    log_level = os.getenv("LOG_LEVEL", "INFO")
    log_file = os.getenv("LOG_FILE")
    setup_logging(console=True, file=log_file, level=log_level)

    # --- Start server ---
    import uvicorn

    uvicorn.run(
        "everstaff.api:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
        reload_excludes=["*.agent*", "*sessions*", "*memory*", "*.venv*"] if args.reload else None,
        log_config=None,
    )


if __name__ == "__main__":
    main()
""",
    "Makefile": """\
.PHONY: install dev run

install:
	uv sync

dev:
	uv run python main.py --reload

run:
	uv run python main.py
""",
    "Dockerfile": """\
FROM python:3.13-slim

WORKDIR /app

# Install uv
RUN pip install uv

# Copy dependency files first for layer caching
COPY pyproject.toml ./
COPY uv.lock* ./

# Copy project files
COPY .agent/ .agent/
COPY agents/ agents/
COPY skills/ skills/
COPY tools/ tools/
COPY builtin_mcp_templates builtin_mcp_templates/
COPY main.py .

# Install dependencies
RUN uv sync --no-dev

EXPOSE 8000

CMD ["uv", "run", "python", "main.py"]
""",
    ".gitignore": """\
# Python
__pycache__/
*.pyc
*.pyo
*.egg-info/
dist/
build/

# Environment
.env
.venv/

# Everstaff runtime data
.agent/sessions/
.agent/memory/
output/

# IDE
.idea/
.vscode/
*.swp

# OS
.DS_Store

# uv
.python-version
""",
    "README.md": """\
# {project_name}

Built with [Everstaff](https://github.com/yuriiiz/everstaff).

## Quick Start

### 1. Install dependencies

```bash
uv sync
```

### 2. Configure environment variables

Copy `.env.example` to `.env` and fill in your API keys:

```bash
cp .env.example .env
```

### 3. Start the server

```bash
uv run python main.py
```

Visit http://localhost:8000 to see the Web UI.

#### CLI options

| Flag | Default | Description |
|------|---------|-------------|
| `--host` | `0.0.0.0` | Bind address |
| `--port` | `8000` | Bind port |
| `--reload` | - | Auto-reload on file changes |

### 4. Docker

```bash
docker build -t {project_name} .
docker run -p 8000:8000 --env-file .env {project_name}
```

## Project Structure

```
.agent/config.yaml             # Framework configuration
main.py                        # Service entry point (with pre_start hook)
agents/                        # YAML agent definitions
skills/                        # Custom skills
tools/                         # Custom Python tools
builtin_mcp_templates/         # Built-in MCP templates
```

## Configuration

Edit `.agent/config.yaml` to configure models, storage, channels, auth, and more.
All available keys are listed with commented examples.
""",
    ".env.example": """\
# LLM API Keys — at least one is required
ANTHROPIC_API_KEY=
# OPENAI_API_KEY=
# GOOGLE_API_KEY=

# Model overrides (optional, overrides model_mappings in config.yaml)
# AGENT_MODEL_SMART=anthropic/claude-sonnet-4-20250514
# AGENT_MODEL_FAST=anthropic/claude-haiku-4-5-20251001

# Lark / Feishu (for HITL channels)
# LARK_APP_ID=
# LARK_APP_SECRET=
# LARK_VERIFICATION_TOKEN=

# Auth (for OIDC / JWT providers)
# OIDC_CLIENT_ID=
# OIDC_CLIENT_SECRET=
# COOKIE_SECRET=
# JWT_SECRET=

# Logging
# LOG_LEVEL=INFO
# LOG_FILE=
""",
}

# Files that are just empty directory markers
DIRS = [
    "agents",
    "skills",
    "tools",
    "builtin_mcp_templates",
]


def init_project(
    target_dir: Path,
    project_name: str,
    force: bool = False,
) -> list[str]:
    """Create scaffold files in *target_dir*. Returns list of created relative paths."""
    created: list[str] = []

    for rel_path, template in TEMPLATES.items():
        dest = target_dir / rel_path
        if dest.exists() and not force:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(template.format(project_name=project_name))
        created.append(rel_path)

    for d in DIRS:
        dir_path = target_dir / d
        dir_path.mkdir(parents=True, exist_ok=True)
        gitkeep = dir_path / ".gitkeep"
        if not gitkeep.exists() or force:
            gitkeep.touch()
            created.append(f"{d}/.gitkeep")

    return created

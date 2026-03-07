# Sandbox Secret Bridge Design

## Problem

Sandbox subprocesses receive API keys via IPC into an in-memory `SecretStore`,
but litellm and mem0 read keys from `os.environ`. Currently LLM calls only work
by accident — litellm's `import`-time `load_dotenv()` finds `.env` on the
directory tree. This fails in Docker sandboxes and is a security concern:
agents can run `env`/`printenv` via Bash to see all environment variables.

## Constraint

Do NOT inject secrets into `os.environ`. The `SecretStore` "never leaks to
environ" design must be preserved.

## Solution

Bridge `SecretStore` to litellm's `CustomSecretManager` interface so all
`get_secret()` calls read from in-memory `SecretStore` without touching
`os.environ`. For mem0's embedder (which bypasses litellm), pass `api_key`
explicitly via config.

## Components

### 1. SecretStoreBridge

New file: `src/everstaff/llm/secret_bridge.py`

A `CustomSecretManager` subclass that wraps `SecretStore`:

```python
class SecretStoreBridge(CustomSecretManager):
    def sync_read_secret(self, secret_name, ...):
        return self._store.get(secret_name)
    async def async_read_secret(self, secret_name, ...):
        return self._store.get(secret_name)

def install_secret_bridge(secret_store):
    litellm.secret_manager_client = SecretStoreBridge(secret_store)
    litellm._key_management_system = KeyManagementSystem.CUSTOM
    litellm._key_management_settings = KeyManagementSettings(access_mode="read_only")
```

### 2. Sandbox entry.py

Call `install_secret_bridge(secret_store)` after IPC auth, before building
`SandboxEnvironment`. This makes all litellm calls (including mem0's internal
litellm LLM calls) read keys from `SecretStore`.

### 3. Mem0Client embedder api_key

mem0's OpenAI embedder reads `api_key` from config or `os.environ`. Since we
don't set `os.environ`, pass it explicitly:

- `Mem0Client.__init__` accepts optional `embedder_api_key: str | None`
- Environment layer resolves the key from `SecretStore` based on the embedder
  provider (e.g. OpenAI → `OPENAI_API_KEY`)
- Passed into mem0 config: `"embedder": {"config": {"api_key": ...}}`

### 4. Non-sandbox path

`DefaultEnvironment` runs in the main process where `os.environ` has keys
(loaded by `load_dotenv()` in `main.py`). No changes needed — litellm and
mem0 continue reading from `os.environ` as before.

## Data Flow (Sandbox)

```
orchestrator os.environ
    ↓ SecretStore.from_environ()
SecretStore (memory)
    ↓ IPC auth
sandbox SecretStore (memory)
    ↓ install_secret_bridge()
litellm CustomSecretManager ← litellm.get_secret() reads from here
    ↓
mem0 litellm LLM ✓ (via litellm get_secret)
mem0 embedder ✓ (via explicit api_key in config)
LiteLLMClient ✓ (via litellm get_secret)
```

## Scope

- New file: `src/everstaff/llm/secret_bridge.py`
- Modified: `src/everstaff/sandbox/entry.py` (add install call)
- Modified: `src/everstaff/memory/mem0_client.py` (accept embedder_api_key)
- Modified: `src/everstaff/sandbox/environment.py` (pass api_key to Mem0Client)
- Modified: `src/everstaff/builder/environment.py` (pass api_key to Mem0Client)
- Tests for SecretStoreBridge, Mem0Client api_key passthrough

# Memory 模块文档

> 源码路径: `src/memory/file_store.py`、`src/nulls.py`（InMemoryStore）、`src/protocols.py`（MemoryStore Protocol）

Memory 模块实现了框架的会话记忆系统，负责对话历史的持久化与恢复。

---

## 1. MemoryStore Protocol (`src/protocols.py`)

```python
@runtime_checkable
class MemoryStore(Protocol):
    async def load(self, session_id: str) -> list[Message]: ...
    async def save(self, session_id: str, messages: list[Message]) -> None: ...
```

### 语义约定

- `load()` — 若 session_id 不存在，返回空列表（不抛出异常）
- `save()` — 全量覆盖写入（不追加），每次保存完整消息历史
- 两个方法均为 `async`，支持异步 I/O

---

## 2. FileMemoryStore (`src/memory/file_store.py`)

### 职责

将会话消息历史以 JSON 格式持久化到本地文件系统，按 `session_id` 独立存储。

### 类定义

```python
class FileMemoryStore:
    def __init__(self, base_dir: str | Path) -> None: ...
    async def load(self, session_id: str) -> list[Message]: ...
    async def save(self, session_id: str, messages: list[Message]) -> None: ...
```

### 存储格式

每个会话对应一个 JSON 文件：`{base_dir}/{session_id}.json`

文件内容为 `Message` 对象列表（完整字段序列化）：

```json
[
  {
    "role": "user",
    "content": "帮我列出当前目录的文件"
  },
  {
    "role": "assistant",
    "content": null,
    "tool_calls": [
      {
        "id": "call_abc123",
        "type": "function",
        "function": {"name": "bash", "arguments": "{\"command\": \"ls -la\"}"}
      }
    ]
  },
  {
    "role": "tool",
    "content": "total 48\n-rw-r--r-- ...",
    "tool_call_id": "call_abc123"
  },
  {
    "role": "assistant",
    "content": "当前目录包含以下文件：..."
  }
]
```

### 实现细节

- 构造时自动创建 `base_dir`（`mkdir(parents=True, exist_ok=True)`）
- `save()` 使用 `ensure_ascii=False` + `indent=2` 格式化，便于人工阅读
- `load()` 完整还原 `Message` 的所有字段（content、tool_calls、tool_call_id、name）

### 使用示例

```python
from src.memory.file_store import FileMemoryStore

store = FileMemoryStore(".agent/sessions")

# 保存会话
await store.save("session-abc-123", messages)

# 恢复会话
messages = await store.load("session-abc-123")
# 若文件不存在，返回 []
```

---

## 3. InMemoryStore (`src/nulls.py`)

### 职责

内存存储，用于测试和无需持久化的场景。

### 实现

```python
class InMemoryStore:
    def __init__(self) -> None:
        self._store: dict[str, list[Message]] = {}

    async def load(self, session_id: str) -> list[Message]:
        return list(self._store.get(session_id, []))

    async def save(self, session_id: str, messages: list[Message]) -> None:
        self._store[session_id] = list(messages)
```

- 返回消息列表的**副本**，防止外部修改影响存储状态
- 进程重启后数据丢失
- 适用于 `TestEnvironment` 和单轮执行场景

---

## 4. 在 AgentRuntime 中的使用

`AgentRuntime.run()` 在每次对话时自动加载和保存消息历史：

```python
async def run(self, user_input: str) -> str:
    # 1. 加载历史
    messages = await self._ctx.memory.load(self._ctx.session_id)

    # 2. 追加用户消息
    messages.append(Message(role="user", content=user_input))

    # 3. 循环（LLM + 工具调用）...

    # 4. 最终保存（只在 is_final 时）
    await self._ctx.memory.save(self._ctx.session_id, messages)
    return response.content or ""
```

注意：当前实现仅在对话结束（`is_final`）时保存。若需要在工具调用间保存（防止中途崩溃丢失），可在工具调用循环内增加 `save()` 调用。

---

## 5. 会话 ID 管理

会话 ID 由 `RuntimeEnvironment.new_session_id()` 生成，默认为 UUID4：

```python
class RuntimeEnvironment:
    def new_session_id(self) -> str:
        return str(uuid4())
```

`AgentContext.session_id` 在构建时由 `AgentBuilder` 注入：

```python
context = AgentContext(
    ...
    session_id=self._env.new_session_id(),
)
```

### 会话恢复

要恢复已有会话，需在构建 `AgentContext` 时传入已知的 `session_id`：

```python
# 自定义 Environment 支持会话恢复
class CLIEnvironment(RuntimeEnvironment):
    def __init__(self, session_id: str | None = None, ...):
        self._session_id = session_id

    def new_session_id(self) -> str:
        return self._session_id or str(uuid4())

# 恢复会话
env = CLIEnvironment(session_id="existing-session-id")
runtime, context = await AgentBuilder(spec, env).build()
# memory.load() 将加载已有历史
response = await runtime.run("继续上次的任务")
```

---

## 6. 自定义存储后端

实现 `MemoryStore` Protocol 即可替换为其他存储：

### SQLite 存储

```python
import aiosqlite
from src.protocols import MemoryStore, Message

class SQLiteMemoryStore:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    async def load(self, session_id: str) -> list[Message]:
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT data FROM sessions WHERE session_id = ?", (session_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return []
                import json
                data = json.loads(row[0])
                return [Message(**m) for m in data]

    async def save(self, session_id: str, messages: list[Message]) -> None:
        import json
        data = json.dumps([m.to_dict() for m in messages])
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO sessions (session_id, data) VALUES (?, ?)",
                (session_id, data),
            )
            await db.commit()
```

### Redis 存储

```python
import redis.asyncio as redis
import json
from src.protocols import Message

class RedisMemoryStore:
    def __init__(self, url: str, ttl: int = 86400) -> None:
        self._client = redis.from_url(url)
        self._ttl = ttl

    async def load(self, session_id: str) -> list[Message]:
        data = await self._client.get(f"session:{session_id}")
        if not data:
            return []
        return [Message(**m) for m in json.loads(data)]

    async def save(self, session_id: str, messages: list[Message]) -> None:
        data = json.dumps([m.to_dict() for m in messages])
        await self._client.setex(f"session:{session_id}", self._ttl, data)
```

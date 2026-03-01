# Tracing 模块文档

> 源码路径: `src/tracing/console.py`、`src/middleware/builtin.py`（TracingMiddleware）、`src/protocols.py`（TracingBackend Protocol）

Tracing 模块实现了框架的可观测性系统，通过 `TracingMiddleware` 在工具执行路径中自动注入追踪事件，支持多后端扩展。

---

## 1. TracingBackend Protocol (`src/protocols.py`)

```python
@runtime_checkable
class TracingBackend(Protocol):
    def on_event(self, event: TraceEvent) -> None: ...
```

任何实现了 `on_event(TraceEvent)` 方法的对象均满足 `TracingBackend` Protocol。

### TraceEvent

```python
@dataclass
class TraceEvent:
    kind: str          # 事件类型
    session_id: str    # 所属会话
    data: dict[str, Any] = field(default_factory=dict)  # 事件负载
```

**内置事件类型：**

| kind | 触发时机 | data 字段 |
|------|---------|-----------|
| `tool_start` | 工具执行开始前 | `tool`, `args` |
| `tool_end` | 工具执行完成后 | `tool`, `is_error`, `content`（截断到200字符） |

> 可通过自定义中间件或 LLMClient 实现 `llm_start`、`llm_end`、`error` 等扩展事件。

---

## 2. ConsoleTracer (`src/tracing/console.py`)

### 职责

将 TraceEvent 打印到标准输出，用于开发调试和 CLI 场景。

### 实现

```python
class ConsoleTracer:
    def on_event(self, event: TraceEvent) -> None:
        print(f"[{event.session_id[:8]}] {event.kind}: {event.data}")
```

输出格式：`[session前8位] 事件类型: 事件数据`

示例输出：

```
[a1b2c3d4] tool_start: {'tool': 'bash', 'args': {'command': 'ls -la'}}
[a1b2c3d4] tool_end: {'tool': 'bash', 'is_error': False, 'content': 'total 48\n-rw-r--r-- 1 user user...'}
```

---

## 3. NullTracer (`src/nulls.py`)

`AgentContext.tracer` 的默认值，静默丢弃所有事件：

```python
class NullTracer:
    def on_event(self, event: TraceEvent) -> None:
        pass  # 静默丢弃
```

用于测试场景和不需要追踪输出的环境。

---

## 4. TracingMiddleware (`src/middleware/builtin.py`)

### 职责

在中间件链中自动在工具执行前后发射 `tool_start` 和 `tool_end` 事件。

### 类定义

```python
class TracingMiddleware:
    def __init__(self, tracer: Any) -> None: ...

    async def __call__(
        self,
        ctx: ToolCallContext,
        next: Callable[[ToolCallContext], Awaitable[ToolResult]],
    ) -> ToolResult:
        # 执行前
        self._tracer.on_event(TraceEvent(
            kind="tool_start",
            session_id=ctx.agent_context.session_id,
            data={"tool": ctx.tool_name, "args": ctx.args},
        ))

        result = await next(ctx)  # 执行后续中间件（最终到达 ExecutionMiddleware）

        # 执行后
        self._tracer.on_event(TraceEvent(
            kind="tool_end",
            session_id=ctx.agent_context.session_id,
            data={
                "tool": ctx.tool_name,
                "is_error": result.is_error,
                "content": result.content[:200],  # 截断，避免日志过大
            },
        ))
        return result
```

### 在链中的位置

```
PermissionMiddleware  →  TracingMiddleware  →  ExecutionMiddleware
                              ↑
                    包裹 ExecutionMiddleware，
                    记录工具的实际执行结果
```

注意：`TracingMiddleware` 在 `PermissionMiddleware` 之后，因此被拒绝的工具调用**不会**产生 `tool_start/tool_end` 事件。如需追踪权限拒绝，可在 `PermissionMiddleware` 后添加自定义中间件。

---

## 5. 自定义追踪后端

实现 `TracingBackend` Protocol 即可：

### 文件追踪（JSONL 格式）

```python
import json
from src.protocols import TraceEvent

class FileTracer:
    def __init__(self, path: str) -> None:
        self._path = path

    def on_event(self, event: TraceEvent) -> None:
        with open(self._path, "a") as f:
            f.write(json.dumps({
                "kind": event.kind,
                "session_id": event.session_id,
                "data": event.data,
            }) + "\n")
```

### WebSocket 实时推送

```python
import asyncio
from src.protocols import TraceEvent

class WebSocketTracer:
    def __init__(self, connection_manager) -> None:
        self._cm = connection_manager

    def on_event(self, event: TraceEvent) -> None:
        # on_event 是同步方法，用 create_task 发起异步推送
        asyncio.create_task(self._cm.broadcast(event.session_id, {
            "type": "trace",
            "kind": event.kind,
            "data": event.data,
        }))
```

### 多后端扇出

```python
class MultiTracer:
    def __init__(self, backends: list) -> None:
        self._backends = backends

    def on_event(self, event: TraceEvent) -> None:
        for backend in self._backends:
            backend.on_event(event)

# 使用
tracer = MultiTracer([ConsoleTracer(), FileTracer("traces.jsonl"), WebSocketTracer(cm)])
```

---

## 6. 在 AgentBuilder 中配置

```python
class MyEnvironment(RuntimeEnvironment):
    def build_tracer(self) -> TracingBackend:
        return MultiTracer([
            ConsoleTracer(),
            FileTracer("logs/traces.jsonl"),
        ])
```

`AgentBuilder` 构建 `TracingMiddleware(tracer)` 并插入中间件链，无需修改 Runtime 或其他模块。

---

## 7. 追踪事件的可观测性模型

```
用户请求
    │
AgentRuntime
    │ 每次工具调用
    ▼
MiddlewareChain
    │
    ├─ [PermissionMiddleware] — 拒绝时不产生 tool_start/tool_end
    │
    ├─ [TracingMiddleware]
    │       │ on_event(tool_start)
    │       ▼
    │   [ExecutionMiddleware] — 执行工具
    │       │
    │       ▼ 结果
    │   on_event(tool_end)  ← 包含 is_error 和 content 摘要
    │
    └─ ToolResult 返回给 Runtime
```

所有工具执行（无论成功或失败）均会产生成对的 `tool_start` + `tool_end` 事件，便于计算延迟和失败率。

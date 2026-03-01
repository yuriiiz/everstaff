# Tools 模块文档

> 源码路径: `src/tools/`、`src/protocols.py`（Tool Protocol）

Tools 模块实现了框架的工具系统，包含 `Tool` Protocol 定义、`DefaultToolRegistry`、中间件链中的 `ExecutionMiddleware`，以及原生工具和 MCP 协议支持。

---

## 1. Tool Protocol (`src/protocols.py`)

### 定义

```python
@runtime_checkable
class Tool(Protocol):
    @property
    def definition(self) -> ToolDefinition: ...
    async def execute(self, args: dict[str, Any]) -> ToolResult: ...
```

任何拥有 `definition` 属性和 `execute` 方法的对象均满足 `Tool` Protocol，无需继承。

### ToolDefinition

工具元数据，用于向 LLM 描述工具能力：

```python
@dataclass
class ToolDefinition:
    name: str           # 工具名（在 ToolRegistry 中唯一）
    description: str    # 向 LLM 描述工具用途
    parameters: dict[str, Any]  # JSON Schema 格式的参数定义
```

示例：

```python
ToolDefinition(
    name="bash",
    description="Execute a bash command and return the output",
    parameters={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "The bash command to run"},
        },
        "required": ["command"],
    },
)
```

### ToolResult

工具执行结果：

```python
@dataclass
class ToolResult:
    tool_call_id: str   # 对应 LLM 的 tool_call id
    content: str        # 结果内容（文本）
    is_error: bool = False  # 是否为错误
```

---

## 2. DefaultToolRegistry (`src/tools/default_registry.py`)

### 职责

按名称管理工具实例，提供工具定义列表（给 LLM）和工具执行能力（给 MiddlewareChain）。

### 类定义

```python
class DefaultToolRegistry:
    def register(self, tool: Tool) -> None: ...
    def get_definitions(self) -> list[ToolDefinition]: ...
    def has_tool(self, name: str) -> bool: ...
    async def execute(self, name: str, args: dict[str, Any], tool_call_id: str) -> ToolResult: ...
```

### 注册行为

- `register()` 若工具名重复，抛出 `ValueError`（防止静默覆盖）
- 工具按注册顺序存储

### 执行行为

`execute()` 有两层错误隔离：

1. **未知工具** — 返回 `ToolResult(is_error=True, content="Unknown tool: 'xxx'")`
2. **工具抛出异常** — 捕获并返回 `ToolResult(is_error=True, content="Tool 'xxx' raised: ...")`

不会向上传播异常，保护 AgentRuntime 循环不被工具错误中断。

### 使用示例

```python
from src.tools.default_registry import DefaultToolRegistry

registry = DefaultToolRegistry()
registry.register(BashTool())
registry.register(ReadTool())

# 获取 LLM 工具定义
definitions = registry.get_definitions()

# 执行工具
result = await registry.execute("bash", {"command": "ls -la"}, "call_123")
```

---

## 3. MiddlewareChain 与工具执行路径

工具调用不直接经过 ToolRegistry，而是通过 MiddlewareChain：

```
AgentRuntime
    │ middleware_chain.execute(ToolCallContext)
    ▼
PermissionMiddleware  →  TracingMiddleware  →  ExecutionMiddleware
                                                    │
                                               registry.execute()
```

### ExecutionMiddleware (`src/middleware/builtin.py`)

```python
class ExecutionMiddleware:
    def __init__(self, registry: ToolRegistry) -> None: ...

    async def __call__(self, ctx: ToolCallContext, next) -> ToolResult:
        return await self._registry.execute(ctx.tool_name, ctx.args, ctx.tool_call_id)
```

ExecutionMiddleware 是链中的**终端中间件**，它调用 `next` 之前直接返回结果（不调用 next）。

### ToolCallContext (`src/middleware/chain.py`)

携带工具调用的完整上下文，在中间件链中传递：

```python
@dataclass
class ToolCallContext:
    tool_name: str
    args: dict[str, Any]
    agent_context: AgentContext    # 可访问所有 Agent 能力
    tool_call_id: str
    metadata: dict[str, Any] = field(default_factory=dict)
```

---

## 4. 原生工具

原生工具位于 `tools/` 目录（项目根目录，非 `src/`），使用 Python 文件实现。每个工具文件暴露一个满足 `Tool` Protocol 的对象：

| 文件 | 工具名 | 功能 |
|------|--------|------|
| `tools/Bash.py` | `bash` | 执行 bash 命令 |
| `tools/Read.py` | `read` | 读取文件内容 |
| `tools/Write.py` | `write` | 写入文件内容 |
| `tools/Edit.py` | `edit` | 精确字符串替换编辑文件 |
| `tools/Glob.py` | `glob` | 文件名模式匹配 |
| `tools/Grep.py` | `grep` | 内容搜索（基于 ripgrep） |

### 实现示例

```python
# tools/Bash.py
from src.protocols import ToolDefinition, ToolResult

class BashTool:
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="bash",
            description="Execute a bash command",
            parameters={
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        )

    async def execute(self, args: dict) -> ToolResult:
        import asyncio
        proc = await asyncio.create_subprocess_shell(
            args["command"],
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await proc.communicate()
        return ToolResult(
            tool_call_id="",
            content=stdout.decode(),
            is_error=proc.returncode != 0,
        )

bash_tool = BashTool()
```

---

## 5. MCP（Model Context Protocol）工具

MCP 工具通过外部 MCP 服务提供，在 `AgentBuilder` 中连接并注册：

### AgentSpec 配置

```yaml
mcp_servers:
  - name: filesystem
    command: npx
    args: [-y, "@modelcontextprotocol/server-filesystem", "/path/to/dir"]
```

### 工作原理

1. `AgentBuilder` 读取 `spec.mcp_servers`
2. 连接 MCP 服务（stdio 或 SSE）
3. 枚举 MCP 暴露的工具
4. 将每个 MCP 工具包装为 `Tool` Protocol 实现
5. 注册到 `ToolRegistry`

MCP 工具对 AgentRuntime 完全透明，与原生工具无差异。

---

## 6. 自定义工具开发

实现 `Tool` Protocol 即可，无需继承任何基类：

```python
from src.protocols import ToolDefinition, ToolResult
from typing import Any

class WeatherTool:
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="get_weather",
            description="Get current weather for a city",
            parameters={
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "City name"},
                },
                "required": ["city"],
            },
        )

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        city = args["city"]
        # ... 调用天气 API
        return ToolResult(tool_call_id="", content=f"Weather in {city}: sunny, 25°C")

# 注册到 registry
registry.register(WeatherTool())
```

---

## 7. SubAgentTool (`src/agents/sub_agent_tool.py`)

子 Agent 作为普通工具注册，是消除循环依赖的核心设计：

```python
class SubAgentTool:
    def __init__(self, spec: SubAgentSpec, env: RuntimeEnvironment) -> None: ...

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=f"task_{self._spec.name}",
            description=f"Delegate task to agent '{self._spec.name}': {self._spec.description}",
            parameters={...},  # 只有一个 "prompt" 参数
        )

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        child_runtime, _ = await AgentBuilder(child_spec, self._env).build()
        response = await child_runtime.run(args["prompt"])
        return ToolResult(tool_call_id="", content=response)
```

**命名规则**: 工具名为 `task_{sub_agent_name}`，避免与其他工具冲突。

**隔离性**: 每次调用都构建新的 `AgentRuntime`，拥有独立的 ToolRegistry、Memory 和 MiddlewareChain，完全隔离。

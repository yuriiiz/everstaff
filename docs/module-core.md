# Core 模块文档

> 源码路径: `src/core/`、`src/builder/`

Core 模块包含框架的三个核心组件：**AgentRuntime**（薄循环层）、**AgentContext**（依赖容器）和 **AgentBuilder**（唯一组装入口）。

---

## 1. AgentRuntime (`core/runtime_v2.py`)

### 职责

AgentRuntime 是核心对话循环，驱动 `LLM 调用 → 工具执行 → 迭代` 的闭环逻辑。设计目标是保持极度精简（~30行），对所有具体实现零感知。

### 类定义

```python
class AgentRuntime:
    def __init__(self, context: AgentContext, llm_client: LLMClient) -> None: ...
    async def run(self, user_input: str) -> str: ...
```

### 构造参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `context` | `AgentContext` | 依赖容器，所有能力通过此访问 |
| `llm_client` | `LLMClient` | LLM 调用客户端（Protocol） |

### 核心循环逻辑

```
run(user_input):
    1. memory.load(session_id)       → 加载历史消息
    2. 追加 Message(role="user")
    3. 循环:
       a. llm_client.complete(messages, tools, system)
       b. 若 response.is_final:
             追加 assistant message
             memory.save(session_id, messages)
             return response.content
       c. 追加 assistant message (含 tool_calls)
       d. for each tool_call:
             tcc = ToolCallContext(tool_name, args, agent_context, tool_call_id)
             result = await middleware_chain.execute(tcc)
             追加 tool result message
       e. 继续循环
```

### 依赖关系

AgentRuntime 只依赖三个模块：

```python
from src.core.context import AgentContext
from src.middleware.chain import ToolCallContext
from src.protocols import LLMClient, Message
```

不知道任何具体实现（不导入 FileMemoryStore、LiteLLMClient、ConsoleTracer 等）。

### 使用示例

```python
# 通过 AgentBuilder 获取 Runtime（推荐）
runtime, context = await AgentBuilder(spec, CLIEnvironment()).build()
response = await runtime.run("帮我列出当前目录的文件")

# 手动构建（测试场景）
env = TestEnvironment()
runtime, context = await AgentBuilder(spec, env).build()
response = await runtime.run("你好")
```

---

## 2. AgentContext (`core/context.py`)

### 职责

AgentContext 是一个 dataclass 依赖容器，持有 Agent 运行所需的全部能力引用。所有字段均为 Protocol 类型，Runtime 通过此容器访问所有能力，无需直接依赖具体实现。

### 类定义

```python
@dataclass
class AgentContext:
    # 必填
    tool_registry: ToolRegistry
    memory: MemoryStore
    middleware_chain: MiddlewareChain

    # 可选（NullObject 默认值）
    tracer: TracingBackend = field(default_factory=NullTracer)
    permissions: PermissionChecker = field(default_factory=AllowAllChecker)
    skill_provider: SkillProvider = field(default_factory=NullSkillProvider)
    knowledge_provider: KnowledgeProvider = field(default_factory=NullKnowledgeProvider)
    sub_agent_provider: SubAgentProvider = field(default_factory=NullSubAgentProvider)

    # 元数据
    session_id: str = field(default_factory=lambda: str(uuid4()))
    system_prompt: str | None = None
```

### 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `tool_registry` | `ToolRegistry` | ✓ | 工具注册表，Runtime 从此获取工具定义和执行工具 |
| `memory` | `MemoryStore` | ✓ | 会话记忆，持久化消息历史 |
| `middleware_chain` | `MiddlewareChain` | ✓ | 中间件链，所有工具调用通过此路由 |
| `tracer` | `TracingBackend` | - | 可观测性后端，默认 NullTracer |
| `permissions` | `PermissionChecker` | - | 权限检查器，默认 AllowAllChecker |
| `skill_provider` | `SkillProvider` | - | 技能提供者，默认 NullSkillProvider |
| `knowledge_provider` | `KnowledgeProvider` | - | 知识库提供者，默认 NullKnowledgeProvider |
| `sub_agent_provider` | `SubAgentProvider` | - | 子 Agent 提供者，默认 NullSubAgentProvider |
| `session_id` | `str` | - | 会话唯一标识，默认 UUID4 |
| `system_prompt` | `str \| None` | - | 系统提示词，由 AgentBuilder 从 spec 注入 |

### NullObject 默认值的意义

可选字段的 NullObject 默认值使得测试和简单场景无需提供完整配置：

```python
# 最小 context，足以运行基础测试
context = AgentContext(
    tool_registry=DefaultToolRegistry(),
    memory=InMemoryStore(),
    middleware_chain=MiddlewareChain([ExecutionMiddleware(registry)]),
)
# tracer → NullTracer（静默）
# permissions → AllowAllChecker（全部放行）
# skill_provider → NullSkillProvider（无技能）
```

---

## 3. AgentBuilder (`builder/agent_builder.py`)

### 职责

AgentBuilder 是**唯一知道所有模块的地方**，负责从 `AgentSpec + RuntimeEnvironment` 组装完整的 `(AgentRuntime, AgentContext)`。所有其他模块互不认识，仅通过 Protocol 通信。

### 类定义

```python
class AgentBuilder:
    def __init__(self, spec: AgentSpec, env: RuntimeEnvironment) -> None: ...
    async def build(self) -> tuple[AgentRuntime, AgentContext]: ...
```

### 构造参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `spec` | `AgentSpec` | Agent YAML 规格，包含 instructions、tools、model 等 |
| `env` | `RuntimeEnvironment` | 运行时环境，决定存储、追踪等具体实现 |

### 组装流程

```python
async def build(self) -> tuple[AgentRuntime, AgentContext]:
    # 1. 并行初始化独立模块
    memory, tracer = await asyncio.gather(
        self._build_memory(),
        self._build_tracer(),
    )
    permissions = self._build_permissions()
    tool_registry = self._build_tool_registry()

    # 2. 显式声明中间件链顺序
    chain = MiddlewareChain([
        PermissionMiddleware(permissions),
        TracingMiddleware(tracer),
        ExecutionMiddleware(tool_registry),
    ])

    # 3. 组装 AgentContext
    context = AgentContext(
        tool_registry=tool_registry,
        memory=memory,
        middleware_chain=chain,
        tracer=tracer,
        permissions=permissions,
        session_id=self._env.new_session_id(),
        system_prompt=self._spec.instructions,
    )

    # 4. 构建 LLM 客户端和 Runtime
    model = getattr(self._spec, "model_override", None) or "gpt-4o-mini"
    llm_client = self._env.build_llm_client(model)
    runtime = AgentRuntime(context=context, llm_client=llm_client)

    return runtime, context
```

### 使用示例

```python
from src.builder.agent_builder import AgentBuilder
from src.builder.environment import CLIEnvironment, TestEnvironment
from src.schema.agent_spec import AgentSpec

# 生产环境
spec = AgentSpec(agent_name="my_agent", instructions="你是一个助手")
runtime, context = await AgentBuilder(spec, CLIEnvironment()).build()
response = await runtime.run("你好")

# 测试环境（使用 mock LLM）
runtime, context = await AgentBuilder(spec, TestEnvironment()).build()
response = await runtime.run("test input")
```

---

## 4. RuntimeEnvironment (`builder/environment.py`)

### 职责

RuntimeEnvironment 抽象了不同运行时（CLI/Web/Test）的差异，使 Agent 定义（AgentSpec）不受运行环境影响。

### 基类接口

```python
class RuntimeEnvironment:
    def build_memory_store(self) -> MemoryStore: ...     # 必须实现
    def build_tracer(self) -> TracingBackend: ...        # 必须实现
    def build_llm_client(self, model: str) -> LLMClient: ...  # 默认 LiteLLMClient
    def new_session_id(self) -> str: ...                 # 默认 UUID4
```

### 内置实现

#### CLIEnvironment

```python
class CLIEnvironment(RuntimeEnvironment):
    def __init__(self, sessions_dir: str = ".agent/sessions") -> None: ...
    def build_memory_store(self) -> FileMemoryStore: ...   # JSON 文件持久化
    def build_tracer(self) -> ConsoleTracer: ...           # 控制台输出
```

#### TestEnvironment

```python
class TestEnvironment(RuntimeEnvironment):
    def build_memory_store(self) -> InMemoryStore: ...     # 内存，无副作用
    def build_tracer(self) -> NullTracer: ...              # 静默
    def build_llm_client(self, model) -> MockLLMClient: ...  # 返回固定响应
```

### 自定义 Environment

```python
class MyWebEnvironment(RuntimeEnvironment):
    def build_memory_store(self) -> MemoryStore:
        return RedisMemoryStore(url=settings.REDIS_URL)

    def build_tracer(self) -> TracingBackend:
        return WebSocketTracer(connection_manager)
```

---

## 5. 数据模型 (`src/protocols.py`)

所有核心数据模型定义在 `src/protocols.py`，零外部依赖：

### Message

对话消息，支持完整的 OpenAI/Anthropic 消息格式：

| 字段 | 类型 | 说明 |
|------|------|------|
| `role` | `str` | `"user"` / `"assistant"` / `"tool"` / `"system"` |
| `content` | `str \| None` | 文本内容 |
| `tool_calls` | `list[dict] \| None` | 工具调用列表（assistant 消息） |
| `tool_call_id` | `str \| None` | 工具调用 ID（tool 消息） |
| `name` | `str \| None` | 工具名称（tool 消息） |

### LLMResponse

LLM 返回结果：

| 字段 | 类型 | 说明 |
|------|------|------|
| `content` | `str \| None` | 文本响应 |
| `tool_calls` | `list[ToolCallRequest]` | 工具调用请求列表 |
| `is_final` | `bool` | 属性：`not self.tool_calls` |

### ToolCallRequest

工具调用请求：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `str` | 唯一调用 ID |
| `name` | `str` | 工具名称 |
| `args` | `dict[str, Any]` | 调用参数 |

### ToolResult

工具执行结果：

| 字段 | 类型 | 说明 |
|------|------|------|
| `tool_call_id` | `str` | 对应的调用 ID |
| `content` | `str` | 结果内容（成功或错误信息） |
| `is_error` | `bool` | 是否为错误结果 |

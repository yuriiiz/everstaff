# 系统架构设计

## 1. 整体架构

Agent Framework 采用分层架构，自顶向下分为**入口层**、**组装层**、**核心运行时层**、**中间件层**、**能力层**和**基础设施层**。所有层通过 `src/protocols.py` 中的 Protocol 接口解耦，依赖方向严格单向。

### 1.1 架构层级

```
┌──────────────────────────────────────────────────────────┐
│  入口层: CLI / FastAPI Server / Python SDK               │
├──────────────────────────────────────────────────────────┤
│  组装层: AgentBuilder + RuntimeEnvironment               │
├──────────────────────────────────────────────────────────┤
│  核心运行时: AgentRuntime + AgentContext                  │
├──────────────────────────────────────────────────────────┤
│  中间件链: PermissionMiddleware → TracingMiddleware       │
│            → ExecutionMiddleware                         │
├──────────────────────────────────────────────────────────┤
│  能力层: ToolRegistry / SkillProvider / KnowledgeProvider│
│          SubAgentTool / WorkflowTool / LiteLLMClient     │
├──────────────────────────────────────────────────────────┤
│  基础设施: FileMemoryStore / RuleBasedChecker / Tracers  │
│            NullObject 默认实现 (nulls.py)                 │
├──────────────────────────────────────────────────────────┤
│  协议层: src/protocols.py (零外部依赖)                    │
└──────────────────────────────────────────────────────────┘
```

### 1.2 入口层

提供三种使用方式，共享同一套核心运行时：

| 入口 | 文件 | 用途 |
|------|------|------|
| CLI | `src/cli.py` | 命令行交互、单次执行、会话管理 |
| Web Server | `src/server.py` | RESTful API + WebSocket 实时流 |
| Python SDK | `AgentBuilder` | 编程方式嵌入到其他系统 |

### 1.3 组装层

`AgentBuilder(spec, env).build()` 是唯一组装入口：
- 接收 `AgentSpec`（来自 YAML）和 `RuntimeEnvironment`（来自入口）
- 并行初始化独立模块（`asyncio.gather`）
- 显式声明中间件链顺序
- 返回 `(AgentRuntime, AgentContext)` 元组

`RuntimeEnvironment` 抽象运行时差异：
- `CLIEnvironment` — FileMemoryStore + ConsoleTracer + LiteLLMClient
- `TestEnvironment` — InMemoryStore + NullTracer + MockLLMClient
- 自定义实现 — 覆盖任意方法即可

### 1.4 核心运行时层

- **AgentRuntime** (`src/core/runtime_v2.py`): ~30行核心循环，只知道 `AgentContext` 和 `LLMClient` 两个 Protocol 接口
- **AgentContext** (`src/core/context.py`): dataclass 依赖容器，所有字段均为 Protocol 类型，可选字段有 NullObject 默认值

### 1.5 中间件层

工具调用经过 FIFO 顺序的中间件链处理：

```
PermissionMiddleware → TracingMiddleware → ExecutionMiddleware
```

每个中间件签名：`async (ctx: ToolCallContext, next) → ToolResult`

第三方中间件只需实现此签名即可零侵入插拔。

### 1.6 能力层

Agent 的所有外部能力均封装为 `Tool` 或 `Provider`：

- **DefaultToolRegistry** — 按名称管理工具，错误隔离（工具异常不影响循环）
- **SkillProvider** — 返回技能工具 + System Prompt 注入
- **KnowledgeProvider** — 返回知识检索工具
- **SubAgentTool** — 子 Agent 封装为普通工具，调用时构建独立运行时
- **WorkflowTool** — DAG 工作流封装为普通工具
- **LiteLLMClient** — 统一 LLM 调用，实现 `LLMClient` Protocol

### 1.7 基础设施层

- **FileMemoryStore** — JSON 文件持久化，按 session_id 存储
- **InMemoryStore** — 内存存储，用于测试
- **RuleBasedChecker** — fnmatch 通配符权限规则，deny 优先
- **ConsoleTracer / NullTracer** — TracingBackend 实现
- **nulls.py** — 所有可选能力的 NullObject 默认实现

---

## 2. 核心数据流

### 2.1 单轮对话数据流

```
用户输入 (user_input)
    │
    ▼
AgentRuntime.run(user_input)
    │
    ├─ memory.load(session_id)  → 加载历史消息
    │
    ├─ 追加 Message(role="user")
    │
    └─ 循环:
         │
         ▼
    llm_client.complete(messages, tools, system)
         │
         ▼
    LLMResponse.is_final?
         │
    ┌────┴────────────────────────────────┐
    │ 是 (无 tool_calls)               否 │
    │                                     │
    ▼                                     ▼
追加 assistant message             追加 assistant message (含 tool_calls)
memory.save(session_id, messages)        │
return response.content                  ▼
                                   for each tool_call:
                                     MiddlewareChain.execute(ToolCallContext)
                                         │
                                         ▼
                                     追加 tool result message
                                         │
                                         └─ 继续循环
```

### 2.2 工具执行数据流（中间件链）

```
ToolCallContext(tool_name, args, agent_context, tool_call_id)
    │
    ▼
PermissionMiddleware
    │ checker.check(tool_name, args)
    │ ─── 拒绝 → ToolResult(is_error=True, "Permission denied")
    │ 通过 ↓
TracingMiddleware
    │ tracer.on_event(TraceEvent(kind="tool_start", ...))
    │
    ▼
ExecutionMiddleware
    │ registry.execute(tool_name, args, tool_call_id)
    │   ─── 未知工具 → ToolResult(is_error=True, "Unknown tool")
    │   ─── 工具异常 → ToolResult(is_error=True, "Tool raised: ...")
    │   ─── 成功 → ToolResult(content=..., is_error=False)
    │
    ▼ (返回时)
TracingMiddleware
    │ tracer.on_event(TraceEvent(kind="tool_end", ...))
    │
    ▼
ToolResult
```

### 2.3 子 Agent 委托数据流

```
父 AgentRuntime 调用 task_{name}(prompt=...)
    │
    ▼
SubAgentTool.execute(args)
    │
    ▼
AgentBuilder(child_spec, env).build()
    │  → 构建独立 AgentRuntime + AgentContext
    │  → 独立 ToolRegistry、Memory、MiddlewareChain
    │
    ▼
child_runtime.run(prompt)
    │  → 子 Agent 完整执行循环
    │
    ▼
返回结果字符串 → ToolResult(content=result)
    │
    ▼
父 AgentRuntime 将结果追加到消息历史，继续循环
```

### 2.4 工作流数据流

```
用户目标 (goal)
    │
    ▼
┌─────────────────────────┐
│ PlanningPhase           │
│  LLM 生成任务 DAG       │
└──────────┬──────────────┘
           ▼
┌─────────────────────────┐
│ HITLGateway             │
│  用户审批计划            │
└──────────┬──────────────┘
           ▼
┌─────────────────────────┐
│ DAGEngine               │
│  按拓扑序并行执行任务    │
│  ┌───┐ ┌───┐ ┌───┐     │
│  │T1 │ │T2 │ │T3 │     │
│  └─┬─┘ └─┬─┘ └─┬─┘     │
│    └──────┼─────┘        │
│           ▼              │
│         ┌───┐            │
│         │T4 │ (依赖T1-T3)│
│         └───┘            │
└──────────┬──────────────┘
           ▼
     ┌─ 有失败? ─┐
     │ 是      否 │
     ▼            ▼
  重规划       返回结果
  (replan)
```

---

## 3. 关键设计模式

### 3.1 Protocol 接口隔离

`src/protocols.py` 是整个框架的根节点，零外部依赖：

```python
@runtime_checkable
class Tool(Protocol):
    @property
    def definition(self) -> ToolDefinition: ...
    async def execute(self, args: dict[str, Any]) -> ToolResult: ...

@runtime_checkable
class MemoryStore(Protocol):
    async def load(self, session_id: str) -> list[Message]: ...
    async def save(self, session_id: str, messages: list[Message]) -> None: ...
```

任何满足 Protocol 结构的对象均可替换，无需继承。

### 3.2 NullObject 模式

`AgentContext` 所有可选字段均有 Null 默认值，测试只需提供最小 context：

```python
@dataclass
class AgentContext:
    tool_registry: ToolRegistry   # required
    memory: MemoryStore           # required
    middleware_chain: MiddlewareChain  # required
    tracer: TracingBackend = field(default_factory=NullTracer)
    permissions: PermissionChecker = field(default_factory=AllowAllChecker)
    skill_provider: SkillProvider = field(default_factory=NullSkillProvider)
    # ...
```

### 3.3 AgentBuilder 集中组装

唯一知道所有模块的地方，其他模块互不认识：

```python
async def build(self) -> tuple[AgentRuntime, AgentContext]:
    # 并行初始化独立模块
    memory, tracer = await asyncio.gather(
        self._build_memory(),
        self._build_tracer(),
    )
    # 显式声明中间件顺序
    chain = MiddlewareChain([
        PermissionMiddleware(permissions),
        TracingMiddleware(tracer),
        ExecutionMiddleware(tool_registry),
    ])
    # 组装 context
    context = AgentContext(tool_registry=..., memory=..., middleware_chain=chain, ...)
    runtime = AgentRuntime(context=context, llm_client=...)
    return runtime, context
```

### 3.4 SubAgent / Workflow 作为工具

消除旧架构中的 `runtime ↔ agents/runner ↔ workflow/coordinator` 三角循环：

```python
class SubAgentTool:
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(name=f"task_{self._spec.name}", ...)

    async def execute(self, args) -> ToolResult:
        child_runtime, _ = await AgentBuilder(child_spec, self._env).build()
        response = await child_runtime.run(args["prompt"])
        return ToolResult(tool_call_id="", content=response)
```

### 3.5 两级懒加载 (Skills)

技能采用两级加载策略减少不必要的 I/O：

- **Level 1**: 仅解析 SKILL.md 的 YAML frontmatter（名称、描述），注入 System Prompt
- **Level 2**: Agent 调用 `use_skill()` 时才读取完整的技能指令

### 3.6 权限合并策略

```
config.yaml permissions  →  合并  ←  agent.yaml permissions
                                │
                                ▼
                        RuleBasedChecker.merge(checkers)
                        deny: 两层取并集（deny 优先）
                        allow: 两层取并集（匹配任一即放行）
```

---

## 4. 依赖方向与循环依赖消除

```
protocols.py              ← 零依赖，根节点
    ↑
nulls.py                  ← 仅依赖 protocols
    ↑
tools/ memory/ tracing/ permissions/ agents/ workflow/
                          ← 各模块仅依赖 protocols，互相不依赖
    ↑
middleware/chain.py       ← 依赖 protocols
middleware/builtin.py     ← 依赖 protocols + chain
    ↑
core/context.py           ← 依赖 protocols + middleware + nulls
core/runtime_v2.py        ← 仅依赖 protocols + context + middleware.chain
    ↑
builder/agent_builder.py  ← 唯一知道所有模块的地方
    ↑
entrypoints (cli.py, server.py)
```

**旧架构的循环依赖问题：**
- `runtime → agents/sub_agent_runner → runtime` （直接循环）
- `runtime → workflow/coordinator → runtime` （间接循环）

**新架构的解法：**
- SubAgent 和 Workflow 封装为 `Tool`，注册到 `ToolRegistry`
- `AgentRuntime` 只看到 `ToolRegistry`（Protocol），不知道具体工具类型
- `AgentBuilder` 在 Runtime 之外负责注册工具，消除循环

---

## 5. 并发与异步模型

- 框架全面使用 `asyncio` 异步模型
- LLM 调用、MCP 连接、工具执行均为异步操作
- `AgentBuilder.build()` 使用 `asyncio.gather` 并行初始化独立模块
- Web Server 使用 FastAPI 的异步请求处理
- WebSocket 使用 `asyncio.Queue` + 双任务模式（监听+发送）
- 工作流 DAG 引擎使用 `asyncio.Semaphore` 控制并行度
- 子 Agent 在独立的异步上下文中运行（每次调用构建新 runtime）

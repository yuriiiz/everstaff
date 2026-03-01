# Agent Framework — 项目设计文档

## 1. 项目概述

Agent Framework 是一个**基于 YAML 声明式配置的 AI Agent 框架**，支持多 LLM 提供商、工具调用、技能系统、知识库、子 Agent 委托和 DAG 工作流编排。框架的核心设计理念是「**配置即 Agent**」— 通过一个 YAML 文件即可定义一个功能完整的 AI Agent，无需编写任何代码。

### 核心特性

| 特性 | 说明 |
|------|------|
| YAML 驱动 | Agent 的所有能力（工具、技能、知识库、子Agent）均通过 YAML 声明 |
| 多模型支持 | 基于 LiteLLM 统一接入 Claude、Gemini、MiniMax 等多种 LLM |
| 工具系统 | 内置 Bash/Read/Write/Edit/Glob/Grep，支持自定义工具和 MCP 协议 |
| 技能系统 | 两级懒加载，支持从社区市场安装技能 |
| 知识库 | 本地目录知识检索，可扩展至向量数据库 |
| 子 Agent | 子 Agent 封装为普通工具，隔离执行，通过 AgentBuilder 独立构建 |
| 工作流引擎 | 基于 DAG 的多 Agent 并行工作流，支持计划-执行-重规划 |
| 上下文管理 | 自动压缩对话窗口，会话持久化（FileMemoryStore）与恢复 |
| 权限控制 | 多级 allow/deny 规则（fnmatch 通配符），框架级与 Agent 级合并 |
| 可观测性 | 多后端 Tracing（控制台、文件），TracingMiddleware 统一注入 |
| 中间件扩展 | MiddlewareChain 插拔横切关注点，第三方可零侵入扩展 |
| Web UI | React + Vite 管理界面，WebSocket 实时交互 |
| CLI | 命令行交互、单次执行、会话恢复 |

---

## 2. 系统架构总览

```
┌─────────────────────────────────────────────────────────────────┐
│                         入口层 (Entry)                          │
│  ┌──────────┐  ┌──────────────────┐  ┌────────────────────────┐ │
│  │   CLI    │  │  FastAPI Server  │  │  Python SDK (直接构建)  │ │
│  │ cli.py   │  │   server.py      │  │  AgentBuilder + env     │ │
│  └────┬─────┘  └───────┬──────────┘  └──────────┬─────────────┘ │
└───────┼────────────────┼─────────────────────────┼──────────────┘
        │                │                         │
        ▼                ▼                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                     组装层 (Builder)                             │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  AgentBuilder(spec, env) → (AgentRuntime, AgentContext)    │ │
│  │  唯一知道所有模块的地方，并行初始化各能力，组装中间件链      │ │
│  └────────────────────────────────────────────────────────────┘ │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  RuntimeEnvironment: CLI / WebServer / Test              │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│                      核心运行时 (Runtime)                        │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  AgentRuntime(context, llm_client)                         │ │
│  │  ~30行核心循环: load messages → LLM → MiddlewareChain      │ │
│  │  只依赖 AgentContext (Protocol接口) + LLMClient            │ │
│  └────────────────────────────────────────────────────────────┘ │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  AgentContext (依赖容器，所有字段均为 Protocol 类型)       │   │
│  │  tool_registry / memory / middleware_chain               │   │
│  │  tracer / permissions / skill_provider / knowledge_provider│  │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│                    中间件链 (MiddlewareChain)                     │
│  [PermissionMiddleware] → [TracingMiddleware] → [ExecutionMiddleware] │
│  第三方实现 MiddlewareCallable 即可零侵入插拔                    │
└─────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│                       能力层 (Capabilities)                      │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────────────────┐ │
│  │ DefaultTool  │ │SkillProvider │ │  KnowledgeProvider       │ │
│  │   Registry   │ │(get_tools,   │ │  (get_tools)             │ │
│  │              │ │ prompt_inj.) │ │                          │ │
│  └──────────────┘ └──────────────┘ └──────────────────────────┘ │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────────────────┐ │
│  │SubAgentTool  │ │  WorkflowTool│ │  LiteLLMClient           │ │
│  │(Tool impl.)  │ │  (Tool impl.)│ │  (LLMClient impl.)       │ │
│  └──────────────┘ └──────────────┘ └──────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│                      基础设施层 (Infrastructure)                  │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────────────────┐ │
│  │FileMemoryStore│ │RuleBasedChecker│ │   ConsoleTracer         │ │
│  │InMemoryStore │ │AllowAllChecker│ │   NullTracer             │ │
│  │(MemoryStore) │ │(PermissionChk)│ │   (TracingBackend)       │ │
│  └──────────────┘ └──────────────┘ └──────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
        ▲
        │ 所有模块依赖
┌───────┴───────────────────────────────────────────────────────┐
│                    协议层 (src/protocols.py)                    │
│  Tool / ToolRegistry / MemoryStore / TracingBackend           │
│  PermissionChecker / SkillProvider / KnowledgeProvider        │
│  LLMClient / ToolDefinition / ToolResult / Message            │
│  TraceEvent / PermissionResult / LLMResponse (零外部依赖)      │
└────────────────────────────────────────────────────────────────┘
```

---

## 3. 项目目录结构

```
agent/
├── agents/                     # Agent YAML 定义文件
├── config/                     # 框架配置
│   └── config.yaml             # 框架全局配置（含模型映射）
├── docs/                       # 项目文档（本目录）
│   └── plans/                  # 设计与实施计划
├── knowledges/                 # 知识库目录
├── skills/                     # 技能目录
├── tools/                      # 原生工具 Python 文件
│   ├── Bash.py / Read.py / Write.py / Edit.py / Glob.py / Grep.py
├── src/                        # 框架源码
│   ├── protocols.py            # ★ 核心：所有 Protocol + 数据模型（零依赖）
│   ├── nulls.py                # NullObject / InMemoryStore 默认实现
│   ├── core/
│   │   ├── context.py          # AgentContext 依赖容器
│   │   └── runtime_v2.py       # ★ AgentRuntime 薄协调层（~30行）
│   ├── middleware/
│   │   ├── chain.py            # MiddlewareChain + ToolCallContext
│   │   └── builtin.py          # ExecutionMiddleware / PermissionMiddleware / TracingMiddleware
│   ├── builder/
│   │   ├── agent_builder.py    # ★ AgentBuilder（唯一知道所有模块的地方）
│   │   └── environment.py      # CLIEnvironment / TestEnvironment
│   ├── llm/
│   │   └── litellm_client.py   # LiteLLMClient（LLMClient Protocol 实现）
│   ├── memory/
│   │   └── file_store.py       # FileMemoryStore（JSON 持久化）
│   ├── tools/
│   │   └── default_registry.py # DefaultToolRegistry
│   ├── permissions/
│   │   └── rule_checker.py     # RuleBasedChecker（fnmatch 通配符）
│   ├── agents/
│   │   └── sub_agent_tool.py   # SubAgentTool（子Agent作为普通工具）
│   ├── tracing/
│   │   └── console.py          # ConsoleTracer
│   ├── workflow/               # DAG 工作流（WorkflowTool 封装）
│   ├── skills/                 # 技能系统
│   ├── knowledge/              # 知识库系统
│   ├── schema/
│   │   └── agent_spec.py       # AgentSpec / SubAgentSpec（Pydantic）
│   └── context/                # 上下文窗口管理
├── web/                        # React + Vite 前端
├── tests/                      # 测试套件
└── pyproject.toml
```

---

## 4. 核心依赖方向

```
protocols.py              ← 零依赖，所有 Protocol 定义
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
entrypoints (cli.py, server.py, test fixtures)
```

**依赖方向完全单向，无循环依赖。**

---

## 5. 关键设计模式

### 5.1 Protocol 接口隔离

所有跨模块通信通过 `src/protocols.py` 中的 `@runtime_checkable Protocol` 进行。Runtime 对所有具体实现零感知：任何满足 Protocol 的对象均可替换。

### 5.2 中间件链 (MiddlewareChain)

工具执行路径：`PermissionMiddleware → TracingMiddleware → ExecutionMiddleware`

每个中间件接收 `(ctx: ToolCallContext, next: Callable)` 并可决定是否调用 `next`。第三方扩展无需修改框架代码。

### 5.3 NullObject 模式

`AgentContext` 所有可选能力字段均有 Null 实现默认值（`NullTracer`、`AllowAllChecker` 等），测试环境只需提供最小 context，无需 mock 全部依赖。

### 5.4 AgentBuilder 工厂

`AgentBuilder(spec, env).build()` 是唯一的组装入口：
- 独立模块并行初始化（`asyncio.gather`）
- 中间件链顺序显式声明
- 不同运行时通过 `RuntimeEnvironment` 差异化（CLI/Web/Test），Agent 定义不变

### 5.5 SubAgent / Workflow 作为工具

子 Agent 和工作流通过注册为普通 `Tool` 接入 `ToolRegistry`，Runtime 完全不知道其存在，消除了旧架构中的三角循环依赖。

---

## 6. 模块文档索引

| 模块 | 文档 | 说明 |
|------|------|------|
| 整体架构 | [architecture.md](./architecture.md) | 架构分层、数据流、设计模式 |
| Core | [module-core.md](./module-core.md) | AgentRuntime、AgentContext、AgentBuilder |
| Tools | [module-tools.md](./module-tools.md) | Tool Protocol、DefaultToolRegistry、MCP、原生工具 |
| Skills | [module-skills.md](./module-skills.md) | 技能系统、SkillProvider |
| Knowledge | [module-knowledge.md](./module-knowledge.md) | 知识库系统、KnowledgeProvider |
| Workflow | [module-workflow.md](./module-workflow.md) | WorkflowTool、DAGEngine |
| Memory | [module-context.md](./module-context.md) | FileMemoryStore、InMemoryStore、MemoryStore Protocol |
| Permissions | [module-permissions.md](./module-permissions.md) | RuleBasedChecker、PermissionMiddleware |
| Tracing | [module-tracing.md](./module-tracing.md) | TracingMiddleware、ConsoleTracer、TracingBackend |
| Server & UI | [module-server.md](./module-server.md) | FastAPI、WebSocket、React UI |
| 快速开始 | [getting-started.md](./getting-started.md) | 安装、配置、使用指南 |

---

## 7. 技术栈

| 层 | 技术 |
|----|------|
| LLM 调用 | LiteLLM（统一多提供商 API） |
| 数据建模 | Pydantic v2 |
| 配置解析 | PyYAML |
| 外部工具 | MCP（Model Context Protocol） |
| Web 服务 | FastAPI + Uvicorn |
| 前端 | React + Vite |
| 会话存储 | 文件系统（JSON） |
| 异步 | asyncio 全面异步 |

---

## 8. 设计原则

1. **Protocol 优先** — 所有跨模块通信通过 Protocol 接口，具体实现可随时替换
2. **单向依赖** — 依赖方向严格从上到下，`protocols.py` 是唯一根节点
3. **NullObject 默认** — 可选能力均有 Null 实现，测试无需 mock 框架内部
4. **中间件横切** — permission、tracing、retry 等横切逻辑通过中间件链统一注入
5. **Builder 集中组装** — AgentBuilder 是唯一知道所有模块的地方，Runtime 对初始化过程零感知
6. **工具即能力** — SubAgent、Workflow 等高级能力均封装为 Tool，统一通过 ToolRegistry 接入
7. **声明式配置** — Agent 由 YAML 完整描述，版本可控、易于分享
8. **环境抽象** — RuntimeEnvironment 隔离 CLI/Web/Test 的差异，Agent 定义不变

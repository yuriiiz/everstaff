# 快速开始指南

本文档指导你从零开始安装、配置和运行 Agent Framework。

---

## 1. 环境要求

| 依赖 | 版本 | 说明 |
|------|------|------|
| Python | >= 3.11 | 核心运行环境 |
| Node.js | >= 18 | 技能安装（npx）和前端（可选） |
| pip / poetry | — | Python 包管理 |

---

## 2. 安装

### 2.1 克隆项目

```bash
git clone <repository-url> agent_framework
cd agent_framework
```

### 2.2 安装 Python 依赖

```bash
pip install -e .
```

或使用 Poetry：

```bash
poetry install
```

### 核心依赖

| 包 | 用途 |
|----|------|
| `litellm` | 多 LLM 提供商统一 API |
| `pydantic` | 数据建模与验证 |
| `pyyaml` | YAML 配置解析 |
| `mcp` | Model Context Protocol |
| `fastapi` | Web API 服务 |
| `uvicorn` | ASGI 服务器 |

---

## 3. 配置

### 3.1 环境变量

创建 `.env` 文件，配置 LLM API 密钥：

```env
# Anthropic Claude
ANTHROPIC_API_KEY=sk-ant-xxx

# 或 MiniMax
MINIMAX_API_BASE=https://api.minimax.chat/v1
MINIMAX_API_KEY=xxx

# 或 Google Gemini
GEMINI_API_KEY=xxx
```

### 3.2 模型配置

编辑 `config/config.yaml` 配置模型映射（`model_mappings` 部分）：

```yaml
model_mappings:
  smart:
    model_id: "claude-sonnet-4-5"     # 或其他支持的模型
    max_tokens: 20000
    temperature: 0.7
    supports_tools: true
    cost_per_input_token: 0.000003
    cost_per_output_token: 0.000015
  fast:
    model_id: "claude-haiku-4-5"
    max_tokens: 20000
    temperature: 0.5
    supports_tools: true
    cost_per_input_token: 0.00000015
    cost_per_output_token: 0.0000006
  reasoning:
    model_id: "claude-sonnet-4-5"
    max_tokens: 20000
    temperature: 1.0
    supports_tools: true
    cost_per_input_token: 0.000015
    cost_per_output_token: 0.000075
```

其他框架配置（`agents_dir`、`storage`、`tracers` 等）通常无需修改，默认值即可使用。

---

## 4. 创建第一个 Agent

### 4.1 编写 Agent YAML

创建文件 `agents/MyAgent.yaml`：

```yaml
agent_name: My Agent
description: 一个简单的助手 Agent
version: 0.1.0
adviced_model_kind: smart
instructions: |
  你是一个乐于助人的 AI 助手。
  你可以使用各种工具来帮助用户完成任务。
  请用中文回答问题。

tools:
  - Bash
  - Read
  - Write
  - Glob
  - Grep

permissions:
  allow:
    - Bash
    - Read
    - Write
    - Glob
    - Grep
  deny: []
```

### 4.2 运行 Agent

#### 交互模式

```bash
python -m agent_framework run agents/MyAgent.yaml
```

输出：

```
Agent 'My Agent' v0.1.0 ready.
Session: abc-123
Type 'exit' or 'quit' to end.

You: 帮我列出当前目录的文件
Agent: 当前目录包含以下文件...

You: exit

--- Session Stats ---
Total tokens: 5,000
  Input:  3,500
  Output: 1,500
Total cost: $0.000150
LLM calls: 2
Tool calls: 1
```

#### 单次执行

```bash
python -m agent_framework run agents/MyAgent.yaml --single "列出当前目录的文件"
```

#### 恢复会话

```bash
python -m agent_framework run agents/MyAgent.yaml --resume abc-123
```

---

## 5. CLI 命令参考

### agent run

```bash
python -m agent_framework run <yaml_path> [options]
```

| 选项 | 说明 |
|------|------|
| `--single MESSAGE` | 单次执行模式 |
| `--resume SESSION_ID` | 恢复会话 |
| `--model-override MODEL` | 覆盖模型（LiteLLM 格式） |
| `--trace [console\|file\|none]` | 追踪模式 |
| `--skills-dir DIR` | 额外技能目录 |
| `--config DIR` | 配置目录路径 |

### agent info

```bash
python -m agent_framework info agents/MyAgent.yaml
```

输出 Agent 元数据、解析的模型、技能、子 Agent 等信息。

### agent skills list

```bash
python -m agent_framework skills list
```

列出所有已发现的技能。

### agent sessions

```bash
# 列出所有会话
python -m agent_framework sessions list

# 按 Agent 过滤
python -m agent_framework sessions list --agent "My Agent"

# 查看会话详情
python -m agent_framework sessions show <session_id>

# 删除会话
python -m agent_framework sessions delete <session_id>
```

---

## 6. 启动 Web 服务

### 启动 API Server

```bash
python -m server
```

Server 运行在 `http://localhost:8000`。

API 文档：`http://localhost:8000/docs`（Swagger UI）

### 启动前端

```bash
cd ui
npm install
npm run dev
```

前端运行在 `http://localhost:5173`。

---

## 7. 进阶配置

### 7.1 添加技能

```yaml
# agents/MyAgent.yaml
skills:
  - find-skills           # 发现和安装技能
  - text-to-speech        # 文字转语音
```

### 7.2 添加知识库

```yaml
# agents/MyAgent.yaml
knowledge_base:
  - type: local_dir
    path: ./knowledges/my_docs
    config:
      max_chunk_size: 2000
```

在 `knowledges/my_docs/` 目录放置 Markdown 或文本文件。

### 7.3 添加子 Agent

```yaml
# agents/MyAgent.yaml
sub_agents:
  Code Writer:
    description: 专注于编写代码的 Agent
    instructions: |
      你是一个代码编写专家。
      收到任务后，使用 Write 工具创建文件。
    adviced_model_kind: inherit
    tools:
      - Write
      - Read
      - Edit
    max_turns: 15
```

### 7.4 添加 MCP 服务

```yaml
# agents/MyAgent.yaml
mcp_servers:
  - name: filesystem
    command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
    transport: stdio
```

### 7.5 配置工作流

```yaml
# agents/MyAgent.yaml
workflow:
  coordinator_instructions: "协调子 Agent 完成复杂任务"
  planning_model_kind: reasoning
  coordinator_model_kind: smart
  max_replans: 2
  max_parallel: 3
```

### 7.6 项目上下文

创建 `.project/CONTEXT.md`：

```markdown
# 项目上下文

这是一个 Python Web 项目，使用 FastAPI 框架。

## 编码规范
- 遵循 PEP 8
- 使用 type hints
```

此内容自动注入所有 Agent 的 System Prompt。

---

## 8. Python SDK 使用

### 基本使用

```python
import asyncio
from core.agent import Agent

async def main():
    agent = await Agent.from_yaml("agents/MyAgent.yaml")

    # 单轮对话
    response = await agent.run("你好，你能做什么？")
    print(response)

    # 多轮对话
    runtime = await agent.run_conversation()
    r1 = await runtime.run_turn("创建一个 hello.py 文件")
    r2 = await runtime.run_turn("运行这个文件")

    await agent.shutdown()

asyncio.run(main())
```

### 自定义工具

```python
from tools.native import tool, NativeTool

@tool(name="weather", description="查询天气")
async def get_weather(city: str) -> str:
    return f"{city} 今天晴，温度 25°C"

agent = await Agent.from_yaml(
    "agents/MyAgent.yaml",
    extra_tools=[get_weather]
)
```

### 自定义 Hook

```python
from hooks.protocol import Hook

class MyHook(Hook):
    async def before_llm_call(self, messages, context):
        print(f"LLM 即将调用，{len(messages)} 条消息")
        return messages

    async def after_tool_call(self, tool_name, result, context):
        print(f"工具 {tool_name} 执行完成")
        return result

agent = await Agent.from_yaml(
    "agents/MyAgent.yaml",
    hooks=[MyHook()]
)
```

---

## 9. 完整 Agent YAML 参考

```yaml
# 基本信息
uuid: null                       # 可选唯一标识
agent_name: My Agent             # Agent 名称（必填）
source: custom                   # builtin / custom / onetime
description: Agent 描述           # 描述
version: 0.1.0                   # 版本号
areas_of_expertise:              # 专长领域
  - general_assistance

# 模型配置
adviced_model_kind: smart        # smart / fast / reasoning
model_override: null             # 直接指定 LiteLLM 模型字符串
temperature: null                # 温度覆盖
max_tokens: null                 # Token 限制覆盖

# 指令
instructions: |
  你是一个 AI 助手...

# 工具
tools:
  - Bash
  - Read
  - Write
  - Edit
  - Glob
  - Grep

# 技能
skills:
  - find-skills

# 知识库
knowledge_base:
  - type: local_dir
    path: ./knowledges/my_docs
    config:
      max_chunk_size: 2000

# MCP 服务
mcp_servers:
  - name: my_server
    command: npx
    args: ["-y", "my-mcp-server"]
    env: {}
    transport: stdio

# 子 Agent
sub_agents:
  Helper:
    description: 辅助 Agent
    instructions: 帮助完成子任务
    adviced_model_kind: inherit  # inherit 继承父 Agent 的模型
    tools:
      - Bash
    max_turns: 20

# 额外上下文文件
context_files: []

# 权限
permissions:
  allow:
    - Bash
    - Read
    - Write
    - Edit
    - Glob
    - Grep
  deny:
    - "Bash(rm -rf:*)"

# 工作流（可选）
workflow:
  coordinator_instructions: "..."
  planning_model_kind: reasoning
  coordinator_model_kind: smart
  max_replans: 3
  max_parallel: 5
  hitl_mode: on_request
```

---

## 10. 常见问题

### Q: 如何切换 LLM 提供商？

修改 `config/config.yaml` 中 `model_mappings` 下的 `model_id`，并在 `.env` 中配置对应的 API Key。LiteLLM 支持的所有模型格式均可使用。

### Q: 如何调试 Agent？

1. 使用 `--trace console` 查看控制台追踪输出
2. 查看 `traces.jsonl` 文件中的详细日志
3. 通过 Web API `/traces` 端点浏览日志

### Q: 如何限制 Agent 的工具权限？

在 Agent YAML 的 `permissions` 中配置 allow/deny 规则。参考 [权限系统文档](./module-permissions.md)。

### Q: 会话数据存储在哪里？

默认存储在项目根目录的 `.sessions/` 目录下，每个会话一个 JSON 文件。

### Q: 如何部署到生产环境？

1. 限制 CORS `allow_origins`
2. 配置适当的权限规则
3. 使用 gunicorn + uvicorn worker 运行
4. 配置文件追踪而非控制台追踪

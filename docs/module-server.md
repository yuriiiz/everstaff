# Server & UI 模块文档

> 源码路径: `src/server.py`、`web/`

Server 模块提供 RESTful API 和 WebSocket 实时通信，UI 模块提供 React + Vite 管理界面。

---

## 1. 概述

### 技术栈

| 组件 | 技术 |
|------|------|
| Web 框架 | FastAPI + Uvicorn |
| WebSocket | FastAPI WebSocket + asyncio.Queue |
| 前端 | React + Vite |
| 实时通信 | WebSocket（双向，LLM 流式输出） |

### 与 AgentBuilder 的关系

FastAPI Server 使用 `AgentBuilder + RuntimeEnvironment` 创建和管理 Agent 实例：

```python
# server.py 中
from src.builder.agent_builder import AgentBuilder
from src.builder.environment import WebServerEnvironment

runtime, context = await AgentBuilder(spec, WebServerEnvironment()).build()
```

---

## 2. FastAPI Server (`src/server.py`)

### API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/agents` | 列出所有 Agent YAML |
| `GET` | `/api/agents/{name}` | 获取指定 Agent 配置 |
| `POST` | `/api/agents/{name}/sessions` | 创建新会话 |
| `GET` | `/api/agents/{name}/sessions` | 列出会话历史 |
| `POST` | `/api/chat` | 单轮对话（同步） |
| `WS` | `/ws/{session_id}` | WebSocket 实时对话 |

### 会话管理

Server 维护 Agent 实例池，按 session_id 隔离：

```python
# 创建会话
POST /api/agents/my_agent/sessions
→ { "session_id": "uuid-xxx" }

# 通过 WebSocket 对话
WS /ws/uuid-xxx
← { "type": "message", "content": "你好！有什么可以帮助你的？" }
→ { "content": "帮我列出文件" }
← { "type": "tool_call", "tool": "bash", "args": {...} }
← { "type": "tool_result", "content": "..." }
← { "type": "message", "content": "当前目录包含以下文件：..." }
```

---

## 3. WebSocket 实时通信

### 消息格式

**客户端 → 服务器（发送消息）：**

```json
{
  "content": "用户消息文本"
}
```

**服务器 → 客户端（事件流）：**

```json
// LLM 开始响应
{ "type": "thinking" }

// 工具调用
{ "type": "tool_call", "tool": "bash", "args": {"command": "ls"} }

// 工具结果
{ "type": "tool_result", "tool": "bash", "content": "file1.py\nfile2.py", "is_error": false }

// 最终文本响应
{ "type": "message", "content": "当前目录包含 2 个文件：file1.py 和 file2.py" }

// 错误
{ "type": "error", "message": "执行失败：..." }
```

### 双任务模式

WebSocket 连接使用双任务架构，避免阻塞：

```python
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()
    queue = asyncio.Queue()

    # 任务1：监听客户端消息
    async def listener():
        async for msg in websocket.iter_json():
            await process_message(msg, queue)

    # 任务2：发送服务器事件
    async def sender():
        while True:
            event = await queue.get()
            await websocket.send_json(event)

    await asyncio.gather(listener(), sender())
```

---

## 4. Tracing 与 WebSocket 集成

WebSocket 场景下可使用 `WebSocketTracer` 将追踪事件实时推送到前端：

```python
class WebServerEnvironment(RuntimeEnvironment):
    def __init__(self, event_queue: asyncio.Queue) -> None:
        self._queue = event_queue

    def build_tracer(self) -> TracingBackend:
        return WebSocketTracer(self._queue)
```

这样工具调用的 `tool_start`/`tool_end` 事件会实时反映在前端 UI 中。

---

## 5. React + Vite 前端 (`web/`)

### 功能

| 页面 | 说明 |
|------|------|
| Agent 列表 | 展示所有可用 Agent，支持创建/编辑 YAML |
| 对话界面 | WebSocket 实时对话，展示工具调用过程 |
| 会话历史 | 列出历史会话，支持恢复 |
| 追踪查看器 | 可视化工具调用链路和 Token 用量 |

### 开发启动

```bash
cd web
npm install
npm run dev   # 开发模式，代理到 :8000
```

### 生产构建

```bash
npm run build  # 构建到 web/dist/
# FastAPI 挂载静态文件服务
app.mount("/", StaticFiles(directory="web/dist", html=True))
```

---

## 6. 启动方式

```bash
# 开发模式（热重载）
uvicorn src.server:app --reload --port 8000

# 生产模式
uvicorn src.server:app --workers 4 --port 8000
```

访问 `http://localhost:8000` 打开管理界面。

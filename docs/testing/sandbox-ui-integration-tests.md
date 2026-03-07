# Sandbox UI Integration Test Cases

> Phase 3-5 sandbox isolation 功能的浏览器端联合测试。
> 测试人员通过 Web UI 操作，对比 sandbox 开启/关闭时的行为差异。

## 前置条件

1. 启动后端服务 `everstaff serve`
2. 打开浏览器访问 Web UI
3. 确保至少有一个 agent 配置了 bash/write/read 等工具

---

## TC-1: 基本对话 — session 创建与消息流

**目的**：验证 sandbox 模式下 session 能正常创建、agent 能正常回复。

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 在 UI 选择一个 agent，发送消息 "你好，请介绍一下自己" | session 创建成功，左侧 session 列表出现新条目，状态为 running |
| 2 | 等待 agent 回复完成 | 消息气泡正常展示，有 text_delta 实时流式输出 |
| 3 | 回复完成后检查 session 状态 | 状态变为 completed 或 waiting（取决于 agent 设计） |
| 4 | 刷新页面，重新打开该 session | 历史消息完整保留（memory.save 通过 IPC proxy 正确持久化） |

**对比点**：sandbox 开启 vs 关闭，消息内容和流式体验应完全一致。

---

## TC-2: 工具调用 — bash 命令执行

**目的**：验证 sandbox 内的 bash 工具能正常执行，输出正确返回。

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 发送 "请执行 `echo hello world`" | UI 展示 tool_call_start（工具名: bash） |
| 2 | 等待工具执行完成 | tool_call_end 显示输出 "hello world" |
| 3 | 发送 "请执行 `pwd`" | 输出应该是 sandbox 的 workspace 目录（如 `/sessions/{sid}/workspaces`），而非服务进程的 cwd |
| 4 | 发送 "请执行 `env \| grep API`" | **关键**：sandbox 模式下不应输出任何 API key 等敏感环境变量（sandbox 用 `_minimal_env()` 隔离） |

**对比点**：
- 非 sandbox 模式 `env` 会泄露所有环境变量
- sandbox 模式 `env` 只有 PATH/HOME/USER/LANG/TERM

---

## TC-3: 文件产物 — FileCreatedEvent 展示

**目的**：验证 agent 创建文件后，UI 能收到 `file_created` 事件并展示文件卡片。

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 发送 "请用 bash 创建一个文件 output.txt，内容写 hello sandbox" | tool_call_start 展示 bash 工具调用 |
| 2 | 工具执行完毕 | UI 出现 **文件卡片**，显示 `output.txt`，类型 text/plain |
| 3 | 发送 "请用 write 工具写一个 report.md 文件" | 同上，UI 展示 report.md 文件卡片，类型 text/markdown |
| 4 | 发送 "请创建一个 data/ 目录并在里面写两个文件" | 应出现多个文件卡片 |
| 5 | 通过 API `GET /sessions/{sid}/files` 检查 | 返回的文件列表应包含以上创建的所有文件 |
| 6 | 通过 API `GET /sessions/{sid}/files/output.txt` 下载 | 文件内容为 "hello sandbox" |

**对比点**：sandbox 和非 sandbox 模式下文件卡片展示应一致。

---

## TC-4: 文件浏览 — workspace 文件列表与下载

**目的**：验证 session 的 workspace 文件能通过 UI 浏览和下载。

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 让 agent 创建几个文件（txt, md, py） | 文件创建成功 |
| 2 | 在 UI 的 session 详情页查看文件列表 | 显示所有已创建文件，包含文件名、大小、修改时间 |
| 3 | 点击某个文件预览 | 文本文件能正常预览内容 |
| 4 | 点击下载按钮 | 文件下载到本地，内容正确 |
| 5 | 让 agent 创建一个子目录结构 `src/main.py` | 文件列表能展示目录层级 |
| 6 | 浏览子目录 `src/` | 显示 main.py |

---

## TC-5: HITL 审批 — 权限请求与人工决策

**目的**：验证需要人工审批的工具调用，在 sandbox 模式下 HITL 流程正常。

**前置**：确保 agent 配置了需要 HITL 审批的工具（或 permission 设置为需要审批）。

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 发送一条会触发需要审批的工具调用的消息 | UI 展示 tool_call_start |
| 2 | 等待 HITL 请求弹出 | UI 出现审批弹窗/卡片，显示工具名、参数、上下文 |
| 3 | session 状态检查 | 状态变为 `waiting_for_human` |
| 4 | 通过 `GET /hitl` API 查看 | 返回一条 pending 的 HITL 请求 |
| 5 | 在 UI 点击 "Approve" | HITL 请求被解决，工具继续执行 |
| 6 | 等待 agent 完成回复 | 回复正常，session 状态恢复 running → completed |
| 7 | 重复步骤 1-2，这次点击 "Reject" | agent 收到拒绝结果，回复中说明工具被拒绝 |

**对比点**：sandbox 模式下 HITL 通过 IPC push 传递（`push_hitl_resolution`），非 sandbox 模式直接内存通知。UI 表现应一致。

---

## TC-6: 取消 session — stop 信号传递

**目的**：验证 sandbox 模式下 session 能被正常取消。

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 发送一条需要较长时间处理的消息（如 "请分析这段很长的代码并给出详细建议"） | agent 开始流式输出 |
| 2 | 在 agent 回复过程中点击 "Stop" 按钮 | 流式输出停止 |
| 3 | 检查 session 状态 | 状态变为 `cancelled` |
| 4 | 刷新页面查看 session | 消息保留到取消时的状态，不丢失已生成内容 |

**对比点**：sandbox 模式通过 IPC push `cancel` 信号，非 sandbox 模式通过 `cancel.signal` 文件。取消速度和行为应一致。

---

## TC-7: session 恢复 — resume 中断的对话

**目的**：验证中断的 session 能被恢复继续对话。

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 创建一个 session 并进行几轮对话 | 正常对话 |
| 2 | 停止该 session（点击 Stop 或关闭页面等待超时） | session 状态变为 cancelled/interrupted |
| 3 | 重新打开该 session | 历史消息完整展示 |
| 4 | 发送新消息继续对话 | agent 基于历史上下文继续回复（memory.load 正确从 IPC proxy 读取） |
| 5 | 检查对话连贯性 | agent 记得之前的对话内容 |

---

## TC-8: 多轮工具调用 — 文件产物累积

**目的**：验证多次工具调用产生的文件产物正确累积展示。

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 发送 "请创建 step1.txt 写入 'step 1 done'" | 出现 step1.txt 文件卡片 |
| 2 | 发送 "请创建 step2.txt 写入 'step 2 done'" | 出现 step2.txt 文件卡片 |
| 3 | 发送 "请修改 step1.txt，追加一行 'updated'" | 出现 step1.txt 的 modified 文件卡片（不是新文件） |
| 4 | 检查文件列表 `GET /sessions/{sid}/files` | 包含 step1.txt 和 step2.txt |
| 5 | 下载 step1.txt | 内容包含 "step 1 done" 和 "updated" 两行 |

**关注点**：每次工具调用前后的 `snapshot_workspace` → `diff_snapshots` 能正确区分 created vs modified。

---

## TC-9: trace 事件 — 调用链追踪

**目的**：验证 sandbox 内的 trace 事件通过 ProxyTracer 正确上报。

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 创建一个包含工具调用的 session | agent 完成回复 |
| 2 | 通过 `GET /sessions/{sid}/traces` 查看 | 返回完整的 trace 事件列表 |
| 3 | 检查 trace 数据 | 包含 session_start、tool_start、tool_end、llm_call 等事件 |
| 4 | 检查 trace 时间戳 | 时间顺序正确，duration_ms 合理 |

**对比点**：sandbox 模式 trace 通过 IPC 火-and-forget 上报，非 sandbox 直接写入。trace 内容应一致。

---

## TC-10: WebSocket 实时推送 — 流式体验

**目的**：验证 WebSocket 通道的实时推送在 sandbox 模式下正常工作。

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 打开浏览器 DevTools → Network → WS tab | 能看到 WebSocket 连接 |
| 2 | 发送消息触发 agent 回复 | WS 收到 `text_delta` 消息流 |
| 3 | 触发工具调用 | WS 收到 `tool_call_start` → `tool_call_end` |
| 4 | 触发文件创建 | WS 收到 `file_created` 事件 |
| 5 | 触发 HITL | WS 收到 `hitl_request` 事件 |
| 6 | 解决 HITL | WS 收到 `hitl_resolved` 事件 |
| 7 | session 完成 | WS 收到 `session_end` 事件 |

**验证方式**：打开 DevTools 的 WS 面板，逐条确认收到的事件类型和数据结构。

---

## TC-11: 并发 session — 多窗口同时对话

**目的**：验证多个 sandbox session 可以并发运行互不干扰。

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 在浏览器标签页 A 创建 session，发送 "创建 a.txt" | Session A 执行 |
| 2 | 同时在标签页 B 创建另一个 session，发送 "创建 b.txt" | Session B 并发执行 |
| 3 | 两个 session 都完成后检查 | Session A 的 workspace 只有 a.txt，Session B 只有 b.txt |
| 4 | 两个 session 的消息互不影响 | 各自独立的对话上下文 |

**关注点**：每个 session 的 ProcessSandbox 有独立的 IPC socket 和 workspace 目录。

---

## TC-12: 超时处理 — 长时间命令

**目的**：验证 sandbox 中超时的命令被正确终止。

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 发送 "请执行 `sleep 600`" | 工具开始执行 |
| 2 | 等待超时（默认 300s，或 agent 配置的 timeout） | 工具返回超时错误 |
| 3 | 检查 agent 回复 | agent 说明命令超时，session 继续正常工作 |
| 4 | 发送新消息 | agent 正常回复（sandbox 未崩溃） |

---

## TC-13: session 统计 — token 用量

**目的**：验证 sandbox 模式下 token 统计正确上报。

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 创建一个多轮对话 session | 正常对话 |
| 2 | 通过 `GET /stats/sessions/{sid}` 查看 | 返回 input_tokens, output_tokens, tool_calls 等统计 |
| 3 | 在 UI 的 session 详情中查看 token 用量 | 数值与 API 一致 |

---

## 通用验证清单

每个 TC 完成后额外检查：

- [ ] 浏览器控制台无 JS 错误
- [ ] WebSocket 连接稳定，无意外断开
- [ ] 页面刷新后 session 数据不丢失
- [ ] session 列表页排序和过滤正常
- [ ] 长消息/大文件不导致 UI 卡顿

## 环境配置参考

```bash
# 启动服务（确保 sandbox 模式开启）
everstaff serve --sandbox-mode process

# 或使用 Docker sandbox 模式
everstaff serve --sandbox-mode docker
```

> 如果当前版本尚未暴露 `--sandbox-mode` CLI 参数，可通过配置文件或环境变量控制 sandbox 开关，具体询问后端开发人员。

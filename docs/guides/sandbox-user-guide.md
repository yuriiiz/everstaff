# Sandbox 使用指南

## 什么是 Sandbox？

Sandbox（沙箱）是一种安全隔离机制。当 AI agent 需要执行命令（比如运行代码、读写文件）时，这些操作会在一个**隔离的环境**中进行，而不是直接在你的服务器上执行。

你可以把它想象成一个"虚拟房间"——agent 在房间里做任何事情，都不会影响到房间外面。

### 不开 Sandbox 会怎样？

- agent 执行的 bash 命令能访问**服务器上所有的环境变量**（包括 API 密钥等敏感信息）
- agent 创建的文件直接写在服务器磁盘上
- 一个 agent 的操作可能意外影响到另一个 agent

### 开了 Sandbox 会怎样？

- agent 只能看到极少数基础环境变量（PATH、HOME 等），**看不到任何 API 密钥**
- 每个 session 有自己独立的工作目录，互不干扰
- 密钥通过安全的内部通道传递，不会暴露在进程环境中

---

## 如何开启 Sandbox

编辑你项目中的配置文件 `.agent/config.yaml`，找到或添加 `sandbox` 部分：

```yaml
# .agent/config.yaml

sandbox:
  enabled: true       # 开启 sandbox
  type: "process"     # 隔离方式（见下方说明）
```

保存后重启服务即可生效。

### 隔离方式（type）

| 值 | 说明 | 适合场景 |
|---|------|---------|
| `process` | 用本地子进程隔离，最简单 | 开发环境、单机部署 |
| `docker` | 用 Docker 容器隔离，更安全 | 生产环境、需要严格隔离 |
| `auto` | 自动选择（有 Docker 用 Docker，没有则用 process） | 不确定时的默认选择 |

**推荐**：如果你只是想先试试，用 `process` 即可。不需要安装任何额外软件。

---

## 完整配置项说明

```yaml
sandbox:
  enabled: true          # true = 开启，false = 关闭（默认关闭）
  type: "process"        # "process" | "docker" | "auto"
  idle_timeout: 300      # 空闲超时（秒）。session 空闲超过这个时间，sandbox 自动回收
  token_ttl: 30          # 内部认证令牌有效期（秒）。一般不需要改

  # Docker 专用配置（仅 type 为 "docker" 时有效）
  docker:
    image: "everstaff/executor:latest"   # Docker 镜像名称
    memory_limit: "512m"                  # 容器内存限制
    cpu_limit: 1.0                        # 容器 CPU 限制（核数）

  # 额外挂载（可选）
  # 如果 agent 需要访问服务器上的某些只读目录，可以在这里配置
  extra_mounts:
    - source: "/data/shared-datasets"     # 服务器上的路径
      target: "/datasets"                 # sandbox 内看到的路径
      readonly: true                      # 是否只读（建议 true）
```

---

## 使用场景

### 场景 1：最简配置（推荐新手）

只需两行：

```yaml
sandbox:
  enabled: true
  type: "process"
```

效果：agent 的所有工具调用在隔离的子进程中执行，环境变量被清理，每个 session 有独立的工作目录。

### 场景 2：Docker 隔离（推荐生产环境）

```yaml
sandbox:
  enabled: true
  type: "docker"
  docker:
    image: "everstaff/executor:latest"
    memory_limit: "1g"
    cpu_limit: 2.0
```

效果：每个 session 运行在独立的 Docker 容器中。需要服务器上安装并运行 Docker。

### 场景 3：需要 agent 访问特定数据

```yaml
sandbox:
  enabled: true
  type: "process"
  extra_mounts:
    - source: "/home/user/documents"
      target: "/docs"
      readonly: true
```

效果：agent 可以读取 `/docs` 下的文件，但无法修改。

---

## 开启后，哪些功能受影响？

### 不受影响（和不开 sandbox 完全一样）

| 功能 | 说明 |
|------|------|
| 对话 | 正常发送消息、接收回复 |
| 流式输出 | 文字实时逐字显示 |
| 历史消息 | 刷新页面后消息保留 |
| 恢复对话 | 中断的 session 可以继续 |
| 文件卡片 | agent 创建的文件在聊天中展示 |
| 文件浏览 | 查看、下载 session 产生的文件 |
| HITL 审批 | 需要人工审批的操作弹出审批请求 |
| 取消 session | 点击 Stop 可以终止运行中的 session |
| Trace 追踪 | 调用链事件正常记录 |
| Token 统计 | 用量统计正常显示 |

### 行为变化

| 功能 | 不开 sandbox | 开了 sandbox |
|------|-------------|-------------|
| 环境变量 | agent 能看到服务器所有环境变量 | agent 只能看到 PATH、HOME、USER 等基础变量 |
| 工作目录 | 可能是服务器的某个共享目录 | 每个 session 有独立的隔离目录 |
| API 密钥传递 | 通过环境变量传递（可被 `env` 命令查看） | 通过安全通道传递（`env` 命令看不到） |
| 进程隔离 | agent 工具在主服务进程中执行 | agent 工具在独立子进程/容器中执行 |

---

## 常见问题

### Q: 开启 sandbox 后 agent 还能正常调用工具吗？

是的。bash、read、write、edit、glob 等所有工具都正常工作。agent 感知不到 sandbox 的存在——它只是在一个干净的环境中执行。

### Q: 开启后会变慢吗？

`process` 模式几乎没有性能差异。`docker` 模式首次启动容器需要 1-2 秒，之后正常。

### Q: 我的 agent 需要访问网络怎么办？

`process` 模式默认允许网络访问。`docker` 模式默认禁止网络（`network_disabled: true`），如需开启，需要在 Docker 配置中修改（联系运维）。

### Q: 我的 agent 需要安装 Python 包怎么办？

`process` 模式下，agent 可以使用 `pip install`（安装在隔离环境中）。`docker` 模式下，需要在 Docker 镜像中预装所需的包。

### Q: sandbox 里的文件和主服务器是什么关系？

每个 session 的文件存储在 `{sessions_dir}/{session_id}/workspaces/` 目录下。这些文件在主服务器上可以通过文件浏览 API 访问和下载，但 agent 无法跨 session 访问其他 session 的文件。

### Q: 如果我不确定是否该开启？

建议开启。`process` 模式零配置成本，且提供了基本的安全隔离。除非你有特殊理由需要 agent 访问服务器完整环境，否则开启 sandbox 是更安全的选择。

---

## 快速检查清单

开启 sandbox 后，你可以这样验证是否生效：

1. 创建一个新 session
2. 让 agent 执行 `env | head -20`
3. 确认输出中**没有** API 密钥等敏感信息
4. 让 agent 执行 `pwd`
5. 确认输出是类似 `.agent/sessions/xxx/workspaces` 的隔离路径
6. 让 agent 创建一个文件，确认文件卡片正常显示

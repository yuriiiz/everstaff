# Workflow 模块文档

> 源码路径: `src/workflow/`

Workflow 模块实现了基于 DAG（有向无环图）的多 Agent 工作流引擎，支持计划生成、人机审批（HITL）、并行执行和失败重规划。工作流封装为普通 `Tool`，通过 ToolRegistry 接入，Runtime 无感知。

---

## 1. 概述

### 核心组件

| 组件 | 文件 | 职责 |
|------|------|------|
| `WorkflowCoordinator` | `coordinator.py` | 工作流总协调器，对外接口 |
| `DAGEngine` | `dag_engine.py` | DAG 拓扑排序 + 并行执行引擎 |

### 工作流作为工具

`WorkflowCoordinator` 将自身封装为 `Tool` 注册到 `ToolRegistry`：

```python
# 在 AgentBuilder 中注册
workflow_tool = WorkflowCoordinatorTool(coordinator)
registry.register(workflow_tool)
```

LLM 可以通过调用此工具来触发工作流执行，AgentRuntime 无需知道工作流的存在。

---

## 2. 工作流数据流

```
用户目标 (goal)
    │
    ▼
┌─────────────────────────┐
│ PlanningPhase           │
│  LLM 分析目标           │
│  生成任务 DAG（JSON）   │
└──────────┬──────────────┘
           ▼
┌─────────────────────────┐
│ HITLGateway             │
│  展示计划给用户          │
│  等待用户审批            │
└──────────┬──────────────┘
           ▼
┌─────────────────────────┐
│ DAGEngine               │
│  拓扑排序任务            │
│  asyncio.Semaphore 控制  │
│  并行执行独立任务         │
│                         │
│  T1 ──┐                 │
│  T2 ──┼─→ T4 (依赖T1-T3)│
│  T3 ──┘                 │
└──────────┬──────────────┘
           ▼
     ┌─ 有失败? ─┐
     │ 是      否 │
     ▼            ▼
  重规划       返回汇总结果
  (replan)
```

---

## 3. DAGEngine (`src/workflow/dag_engine.py`)

### 职责

按拓扑顺序并行执行任务，每个任务由独立的子 Agent 执行。

### 核心算法

```
1. 构建任务依赖图（邻接表）
2. 计算每个任务的入度（依赖数量）
3. 初始化就绪队列（入度为0的任务）
4. 循环直到所有任务完成：
   a. 并行执行所有就绪任务（asyncio.gather）
   b. 每个任务完成后，更新依赖此任务的任务的入度
   c. 入度变为0的任务加入就绪队列
5. 返回所有任务结果
```

### 并行控制

使用 `asyncio.Semaphore` 控制最大并发度：

```python
semaphore = asyncio.Semaphore(max_parallel)  # 默认 4

async def execute_task(task):
    async with semaphore:
        # 构建子 Agent 并执行
        runtime, _ = await AgentBuilder(task.spec, env).build()
        return await runtime.run(task.prompt)
```

---

## 4. WorkflowCoordinator (`src/workflow/coordinator.py`)

### 职责

管理完整的工作流生命周期：计划生成 → HITL 审批 → DAG 执行 → 重规划。

### 主要方法

| 方法 | 说明 |
|------|------|
| `run_workflow(goal, context)` | 完整工作流入口 |
| `_plan(goal, context)` | 调用 LLM 生成任务 DAG |
| `_hitl_gate(plan)` | 展示计划，等待用户审批 |
| `_execute(plan)` | DAGEngine 并行执行 |
| `_replan(failed_tasks, results)` | 基于失败任务重规划 |

### 任务 DAG 数据结构

LLM 生成的计划是 JSON 格式的任务列表：

```json
{
  "tasks": [
    {
      "id": "T1",
      "name": "分析需求",
      "prompt": "分析以下需求文档...",
      "agent": "analyst",
      "depends_on": []
    },
    {
      "id": "T2",
      "name": "设计架构",
      "prompt": "基于需求设计系统架构...",
      "agent": "architect",
      "depends_on": ["T1"]
    },
    {
      "id": "T3",
      "name": "实现功能",
      "prompt": "根据架构实现以下功能...",
      "agent": "developer",
      "depends_on": ["T2"]
    }
  ]
}
```

---

## 5. AgentSpec 配置

```yaml
# agents/orchestrator.yaml
agent_name: orchestrator
instructions: "你是一个工作流协调器..."
workflow:
  enabled: true
  max_parallel: 4
  max_replan_attempts: 2
  sub_agents:
    analyst:
      description: "需求分析专家"
      instructions: "你是一名专业的需求分析师..."
    architect:
      description: "系统架构专家"
      instructions: "你是一名经验丰富的系统架构师..."
    developer:
      description: "全栈开发工程师"
      instructions: "你是一名熟练的全栈开发工程师..."
```

---

## 6. HITL（Human-in-the-Loop）机制

工作流在执行前会展示计划并等待用户确认：

```
[Workflow Plan]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Task 1: 分析需求
  Agent: analyst
  Depends: (none)

Task 2: 设计架构
  Agent: architect
  Depends: T1

Task 3: 实现功能
  Agent: developer
  Depends: T2
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Continue? [y/n]:
```

用户可以：
- 确认执行（`y`）
- 拒绝并修改目标（`n`）
- 修改计划后重新生成

---

## 7. 重规划机制

当任务执行失败时，`WorkflowCoordinator` 调用 LLM 进行重规划：

```
失败任务: T3 (实现功能)
已完成任务: T1 (需求分析), T2 (架构设计)

重规划 prompt:
"以下任务失败了：...
已完成的任务结果：...
请生成修正后的任务计划..."
```

重规划次数受 `max_replan_attempts` 限制，超限后返回部分结果并报告失败。

# Skills 模块文档

> 源码路径: `src/skills/`

Skills 模块实现了框架的技能系统，支持两级懒加载和 `SkillProvider` Protocol 接入。技能是预定义的指令集，Agent 可按需加载，避免 System Prompt 过长。

---

## 1. 概述

### 设计目标

- **按需加载** — Level 1 只加载元数据，Level 2 才加载完整指令
- **System Prompt 注入** — 将可用技能列表注入 System Prompt，让 LLM 知道何时调用
- **Protocol 接入** — 通过 `SkillProvider` Protocol 接入 `AgentContext`，Runtime 无感知

### 与工具的关系

技能本质上是**注入到 System Prompt 的指令集**，不同于工具（Tool）的函数调用形式。技能通过以下方式暴露给 Agent：

1. `SkillProvider.get_system_prompt_injection()` — 将 Level 1 元数据注入 System Prompt
2. `SkillProvider.get_tools()` — 提供 `use_skill(skill_name)` 工具，供 LLM 调用加载完整指令

---

## 2. SkillProvider Protocol (`src/protocols.py`)

```python
@runtime_checkable
class SkillProvider(Protocol):
    def get_tools(self) -> list[Tool]: ...
    def get_system_prompt_injection(self) -> str: ...
```

### 方法说明

| 方法 | 返回 | 说明 |
|------|------|------|
| `get_tools()` | `list[Tool]` | 返回技能相关工具（如 `use_skill`） |
| `get_system_prompt_injection()` | `str` | 返回注入 System Prompt 的技能目录文本 |

---

## 3. 两级懒加载

### Level 1 — 元数据加载

启动时扫描 `skills/` 目录，只解析每个技能的 YAML frontmatter：

```markdown
---
name: code-review
description: 对代码进行专业的代码审查，检查代码质量、安全性和最佳实践
version: 1.0.0
---
# Code Review 技能

完整指令内容...（Level 2 才读取）
```

Level 1 提取：`name`、`description`、`version`，生成 System Prompt 注入文本。

### Level 2 — 完整指令加载

当 LLM 调用 `use_skill(skill_name)` 时，才读取完整的技能文件内容，并将其注入当前对话上下文。

```
Agent 调用: use_skill("code-review")
    │
    ▼
读取 skills/code-review/SKILL.md 完整内容
    │
    ▼
返回完整技能指令（作为工具结果）
    │
    ▼
LLM 阅读指令后，按指令执行任务
```

---

## 4. 技能目录结构

```
skills/
├── code-review/
│   └── SKILL.md          # 技能定义文件（YAML frontmatter + Markdown 指令）
├── git-workflow/
│   └── SKILL.md
└── python-expert/
    └── SKILL.md
```

### SKILL.md 格式

```markdown
---
name: code-review
description: 专业代码审查，检查质量、安全性和最佳实践
version: 1.0.0
---

# Code Review 技能

## 你的角色

你是一名专业的代码审查专家...

## 审查清单

1. 代码可读性
2. 安全漏洞
3. 性能问题
...
```

---

## 5. NullSkillProvider (`src/nulls.py`)

`AgentContext.skill_provider` 的默认值，无技能能力：

```python
class NullSkillProvider:
    def get_tools(self) -> list[Tool]:
        return []

    def get_system_prompt_injection(self) -> str:
        return ""
```

---

## 6. AgentSpec 配置

```yaml
# agents/my_agent.yaml
skills:
  - code-review
  - git-workflow
```

`AgentBuilder` 根据 `spec.skills` 初始化 `SkillProvider`，并将返回的工具注册到 `ToolRegistry`，将 prompt injection 写入 `AgentContext.system_prompt`。

---

## 7. System Prompt 注入示例

当 Agent 配置了技能时，System Prompt 会包含类似：

```
## Available Skills

You have access to the following skills. Use `use_skill(name)` to load detailed instructions.

- **code-review** (v1.0.0): 专业代码审查，检查质量、安全性和最佳实践
- **git-workflow** (v1.0.0): Git 工作流规范，包含提交规范和分支管理
```

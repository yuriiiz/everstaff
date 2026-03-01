# Knowledge 模块文档

> 源码路径: `src/knowledge/`

Knowledge 模块实现了框架的知识库系统，使 Agent 能够检索和引用外部知识源。通过 `KnowledgeProvider` Protocol 接入 `AgentContext`，Runtime 无感知。

---

## 1. 概述

### 设计目标

- **知识工具化** — 知识检索暴露为 `Tool`，LLM 主动调用以获取相关知识
- **Protocol 接入** — 通过 `KnowledgeProvider` Protocol 接入 AgentContext
- **可扩展后端** — 支持本地文件检索，可扩展至向量数据库

### 与技能的区别

| 对比项 | Skills | Knowledge |
|--------|--------|-----------|
| 内容类型 | 操作指令集 | 参考文档/数据 |
| 触发方式 | `use_skill(name)` | `search_knowledge(query)` |
| 加载时机 | 按需懒加载 | 按查询动态检索 |
| System Prompt | 注入技能目录 | 注入知识源目录 |

---

## 2. KnowledgeProvider Protocol (`src/protocols.py`)

```python
@runtime_checkable
class KnowledgeProvider(Protocol):
    def get_tools(self) -> list[Tool]: ...
```

`get_tools()` 返回知识库相关工具，通常包括：
- `search_knowledge(query)` — 全文搜索知识库
- `get_knowledge_document(path)` — 获取指定文档全文

---

## 3. 知识库目录结构

```
knowledges/
├── api-docs/
│   ├── README.md         # 知识源描述（YAML frontmatter）
│   ├── endpoints.md
│   └── authentication.md
├── company-policies/
│   ├── README.md
│   └── code-of-conduct.md
└── technical-specs/
    ├── README.md
    └── architecture.md
```

### README.md 格式（知识源描述）

```markdown
---
name: api-docs
description: API 文档，包含所有接口定义和认证方式
version: 1.0.0
---
```

---

## 4. NullKnowledgeProvider (`src/nulls.py`)

`AgentContext.knowledge_provider` 的默认值，无知识库能力：

```python
class NullKnowledgeProvider:
    def get_tools(self) -> list[Tool]:
        return []
```

---

## 5. AgentSpec 配置

```yaml
# agents/my_agent.yaml
knowledge_base:
  - name: api-docs
    path: ./knowledges/api-docs
    type: local_directory

  - name: company-policies
    path: ./knowledges/company-policies
    type: local_directory
```

`AgentBuilder` 根据 `spec.knowledge_base` 初始化 `KnowledgeProvider`，并将返回的工具注册到 `ToolRegistry`。

---

## 6. 检索流程

```
LLM 调用: search_knowledge(query="认证方式")
    │
    ▼
KnowledgeProvider 后端执行检索
    │  （全文搜索 / 向量相似度搜索）
    │
    ▼
返回相关文档片段列表
    │
    ▼
LLM 基于检索结果生成回答
```

---

## 7. 可扩展后端

`KnowledgeBackend` Protocol 定义了后端接口，支持替换为向量数据库：

```python
# 本地文件系统后端（默认）
class LocalDirectoryBackend:
    def search(self, query: str, top_k: int = 5) -> list[DocumentChunk]: ...
    def get_document(self, path: str) -> str: ...

# 向量数据库后端（可扩展）
class ChromaBackend:
    def __init__(self, collection_name: str) -> None: ...
    def search(self, query: str, top_k: int = 5) -> list[DocumentChunk]: ...
    def get_document(self, path: str) -> str: ...
```

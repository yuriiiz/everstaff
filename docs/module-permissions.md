# Permissions 模块文档

> 源码路径: `src/permissions/rule_checker.py`、`src/middleware/builtin.py`（PermissionMiddleware）

Permissions 模块实现了框架的工具调用权限控制系统，通过 `RuleBasedChecker` 和 `PermissionMiddleware` 在工具执行前进行规则检查。

---

## 1. PermissionChecker Protocol (`src/protocols.py`)

```python
@runtime_checkable
class PermissionChecker(Protocol):
    def check(self, tool_name: str, args: dict[str, Any]) -> PermissionResult: ...
```

### PermissionResult

```python
@dataclass
class PermissionResult:
    allowed: bool
    reason: str | None = None  # 拒绝时提供原因
```

---

## 2. RuleBasedChecker (`src/permissions/rule_checker.py`)

### 职责

基于 allow/deny 规则列表的权限检查器，支持 fnmatch 通配符，实现 deny 优先语义。

### 类定义

```python
class RuleBasedChecker:
    def __init__(self, allow: list[str], deny: list[str]) -> None: ...
    def check(self, tool_name: str, args: dict[str, Any]) -> PermissionResult: ...

    @classmethod
    def merge(cls, checkers: list[RuleBasedChecker]) -> RuleBasedChecker: ...
```

### 检查逻辑

```
check(tool_name, args):
    1. 遍历 deny 规则：
       如果 fnmatch(tool_name, pattern) → 返回 PermissionResult(allowed=False, reason=...)

    2. 如果 allow 列表为空 → 返回 PermissionResult(allowed=True)  # 开放模式

    3. 遍历 allow 规则：
       如果 fnmatch(tool_name, pattern) → 返回 PermissionResult(allowed=True)

    4. 无匹配 → 返回 PermissionResult(allowed=False, reason="not in allow list")
```

**关键语义：**
- **deny 优先** — deny 规则先检查，匹配即拒绝，不受 allow 影响
- **空 allow = 开放** — allow 列表为空时，通过 deny 检查即放行（全允许模式）
- **非空 allow = 白名单** — allow 列表非空时，工具名必须匹配至少一条 allow 规则

### 通配符示例

```python
# 允许所有 bash 变体，拒绝危险操作
checker = RuleBasedChecker(
    allow=["bash*", "read*", "glob*", "grep*"],
    deny=["bash_sudo", "write_system*"],
)

checker.check("bash", {})          # PermissionResult(allowed=True)
checker.check("bash_sudo", {})     # PermissionResult(allowed=False, reason="Matched deny rule 'bash_sudo'")
checker.check("unknown_tool", {})  # PermissionResult(allowed=False, reason="'unknown_tool' not in allow list")
```

支持的通配符模式（fnmatch）：

| 模式 | 匹配示例 |
|------|---------|
| `bash` | 精确匹配 "bash" |
| `bash*` | "bash", "bash_safe", "bash_exec" |
| `*write*` | "write", "file_write", "db_write" |
| `task_*` | "task_agent1", "task_researcher" |
| `*` | 任意工具名 |

### merge() 方法

合并多个 checker 的规则，用于框架级与 Agent 级权限叠加：

```python
@classmethod
def merge(cls, checkers: list[RuleBasedChecker]) -> RuleBasedChecker:
    """Union of all deny rules; union of all allow rules."""
    all_deny = []
    all_allow = []
    for c in checkers:
        all_deny.extend(c._deny)
        all_allow.extend(c._allow)
    return cls(allow=all_allow, deny=all_deny)
```

**合并语义：**
- deny 取并集（任一 checker 拒绝即拒绝）
- allow 取并集（任一 checker 放行即放行）

### 使用示例

```python
from src.permissions.rule_checker import RuleBasedChecker

# 框架级权限（来自 config.yaml）
framework_checker = RuleBasedChecker(
    allow=["bash", "read", "write", "edit", "glob", "grep"],
    deny=["bash_rm_rf", "write_etc*"],
)

# Agent 级权限（来自 agent.yaml）
agent_checker = RuleBasedChecker(
    allow=["bash", "read"],
    deny=["write*"],  # 此 Agent 不允许写文件
)

# 合并（更严格的限制生效）
merged = RuleBasedChecker.merge([framework_checker, agent_checker])
```

---

## 3. NullObject 实现 (`src/nulls.py`)

`AgentContext.permissions` 的默认值是 `AllowAllChecker`：

```python
class AllowAllChecker:
    def check(self, tool_name: str, args: dict) -> PermissionResult:
        return PermissionResult(allowed=True)

class DenyAllChecker:
    def check(self, tool_name: str, args: dict) -> PermissionResult:
        return PermissionResult(allowed=False, reason="All tools denied")
```

- `AllowAllChecker` — 开发和测试环境的默认选择，无需配置权限
- `DenyAllChecker` — 沙箱场景，所有工具调用均被拒绝

---

## 4. PermissionMiddleware (`src/middleware/builtin.py`)

### 职责

在中间件链中作为第一道拦截，在工具实际执行前检查权限。

### 类定义

```python
class PermissionMiddleware:
    def __init__(self, checker: PermissionChecker) -> None: ...

    async def __call__(
        self,
        ctx: ToolCallContext,
        next: Callable[[ToolCallContext], Awaitable[ToolResult]],
    ) -> ToolResult:
        result = self._checker.check(ctx.tool_name, ctx.args)
        if not result.allowed:
            return ToolResult(
                tool_call_id=ctx.tool_call_id,
                content=f"Permission denied for '{ctx.tool_name}': {result.reason}",
                is_error=True,
            )
        return await next(ctx)
```

### 在链中的位置

```
PermissionMiddleware  →  TracingMiddleware  →  ExecutionMiddleware
        ↑
    第一道检查，拒绝时直接返回，不调用 next
```

拒绝时返回带 `is_error=True` 的 ToolResult，不抛出异常，保证 AgentRuntime 循环正常继续（LLM 会看到权限拒绝信息并作出响应）。

---

## 5. 权限配置

### YAML 配置

框架级权限（`config/config.yaml`）：

```yaml
permissions:
  allow:
    - bash
    - read
    - write
    - edit
    - glob
    - grep
  deny: []
```

Agent 级权限（`agents/my_agent.yaml`）：

```yaml
permissions:
  allow:
    - read
    - glob
    - grep
  deny:
    - write
    - bash
```

### 合并策略

`AgentBuilder` 负责从两层配置构建最终的 `RuleBasedChecker`：

```python
framework_checker = RuleBasedChecker(
    allow=framework_config.permissions.allow,
    deny=framework_config.permissions.deny,
)
agent_checker = RuleBasedChecker(
    allow=spec.permissions.allow,
    deny=spec.permissions.deny,
)
final_checker = RuleBasedChecker.merge([framework_checker, agent_checker])
```

**实际效果：** Agent 级的 deny 规则会叠加到框架级之上，Agent 只能访问两层 allow 规则的并集中未被任一层 deny 的工具。

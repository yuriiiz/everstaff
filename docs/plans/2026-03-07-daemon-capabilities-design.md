# Daemon Autonomous Capabilities Upgrade Design

## Context

The daemon currently has a solid wake-think-act-reflect loop with cron/interval triggers, LLM decision-making, and HITL support. However, to achieve an "always-on autonomous agent" that discovers needs, solves them, and continuously evolves, several capability gaps need to be addressed.

## Gap Analysis

| Capability | Current | Target | Gap |
|---|---|---|---|
| Scheduled triggers | cron/interval via APScheduler | Keep | None |
| External signal intake | Only SchedulerSensor | Webhook, FileWatch, etc. | Need new sensor implementations |
| Need discovery (code/repo) | None | Monitor PRs, CI, deps | Need sensors + agent config |
| Need discovery (external) | None | Messages, tickets, alerts | Need WebhookSensor |
| Self-discovery | Episodes exist but no analysis loop | Analyze history, find improvements | Need learning cycle |
| Long-term goal management | Static GoalConfig in YAML | User goals immutable + daemon breakdown | Need goal breakdown mechanism |
| Self-evolution (skills/tools/instructions) | None | Modify own skills, MCP, instructions via tools | Need self-mutation tools |
| Self-evolution (permissions) | N/A | FORBIDDEN | Hard constraint |
| Sensor abstraction | Duck typing | Formal ABC | Need formalization |
| Feedback learning loop | Episodes write-only | Closed-loop learning from results | Need learning cycle |

## Design

### 1. Sensor Abstraction Formalization

Formalize the implicit sensor interface into an ABC.

```python
class Sensor(ABC):
    @abstractmethod
    async def start(self, event_bus: EventBus) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...
```

Sensor hierarchy:

```
Sensor (ABC)
  SchedulerSensor     -- already exists, refactor to extend ABC
  WebhookSensor       -- new: receives external HTTP push
  FileWatchSensor     -- new: monitors file/directory changes
  InternalSensor      -- new: monitors internal events (episode count, goal progress)
```

PollSensor is deferred to a future phase.

### 2. WebhookSensor

Registers a FastAPI endpoint on the shared app:

```
POST /api/daemon/webhook/{agent_uuid}
```

- Uses agent UUID (not name) for uniqueness
- Receives arbitrary JSON payload
- Publishes AgentEvent with source="webhook", type from payload or path
- Validates agent_uuid exists and has autonomy enabled
- Supports optional signature verification (HMAC) for security

Configuration in agent YAML:

```yaml
autonomy:
  triggers:
    - id: github-pr
      type: webhook
      task: "Review the incoming PR event and decide what action to take"
```

On daemon startup, WebhookSensor registers routes for all webhook-type triggers. Hot reload adds/removes routes dynamically.

### 3. FileWatchSensor

Uses `watchfiles` (async file watcher) to monitor specified paths.

Configuration:

```yaml
autonomy:
  triggers:
    - id: config-change
      type: file_watch
      watch_paths:
        - "config/"
        - "agents/"
      task: "A config file changed, analyze the change and respond"
```

Publishes AgentEvent with source="file_watch", payload includes changed file paths and change type (created/modified/deleted).

### 4. InternalSensor

Monitors daemon-internal state and emits events when thresholds are met.

Trigger types:
- `episode_count`: fires after N episodes accumulated (min 5)
- `goal_stale`: fires when a goal has no progress for N cycles
- `error_rate`: fires when failure rate exceeds threshold

Configuration:

```yaml
autonomy:
  triggers:
    - id: self-reflection
      type: internal
      condition: episode_count
      threshold: 5
      task: "Analyze recent execution episodes and extract learning insights"
```

InternalSensor subscribes to EventBus to count relevant events and fires when threshold is reached.

### 5. Long-term Goal Management

#### Principle: User goals are immutable source of truth

```
GoalConfig (YAML, user-defined, READ-ONLY)
    |
    v
GoalBreakdown (daemon-maintained, persisted)
    +-- sub_goal_1: { description, status, progress, acceptance_criteria }
    +-- sub_goal_2: { description, status, progress, acceptance_criteria }
    +-- ...
```

#### New tool for ThinkEngine: `break_down_goal`

```python
# Available to ThinkEngine during think phase
def break_down_goal(
    goal_id: str,           # references GoalConfig.id
    sub_goals: list[dict],  # [{description, acceptance_criteria}]
) -> str:
    """Break a user goal into actionable sub-goals. User's original goal is preserved."""
```

#### New tool: `update_goal_progress`

```python
def update_goal_progress(
    goal_id: str,
    sub_goal_index: int,
    status: str,        # "pending" | "in_progress" | "completed" | "blocked"
    progress_note: str,
) -> str:
```

Storage: GoalBreakdown persisted alongside working memory (exact storage depends on memory module redesign).

ThinkEngine receives both user GoalConfig and daemon GoalBreakdown in context to inform decisions.

### 6. Self-Mutation Tools

Daemon-only tools that allow agents to modify their own configuration. All mutations require HITL approval.

#### Tools

| Tool | Purpose | Scope |
|---|---|---|
| `update_agent_skills` | Add/remove/modify skills | skills field in agent YAML |
| `update_agent_mcp` | Add/remove MCP server configs | mcp_servers field |
| `update_agent_instructions` | Modify system instructions | instructions field |
| `update_agent_triggers` | Add/modify triggers | autonomy.triggers field |
| `update_agent_goals` | Manage daemon's own sub-goals | GoalBreakdown only, not user GoalConfig |

#### Hard Constraints

- FORBIDDEN: Any mutation touching `permissions`, `allow`, `deny` fields
- Every tool performs a pre-flight check rejecting permission-related changes
- Every mutation raises HITL request describing the proposed change before applying
- HITL request includes: what will change, current value, proposed value, reasoning

#### Flow

```
Agent decides to add a new skill
  |
  v
Calls update_agent_skills(action="add", skill={...})
  |
  v
Tool constructs HITL request:
  "I want to add skill 'code-review' to my capabilities.
   Reason: I've noticed repeated code review requests in recent episodes.
   Proposed change: [diff preview]"
  |
  v
Broadcasts to HITL channels, waits for human approval
  |
  v
If approved: write to agent YAML, trigger hot reload
If rejected: record decision in memory, do not apply
```

### 7. Feedback Learning Cycle

#### Trigger

InternalSensor fires `self.reflection.due` when episode count reaches threshold (minimum 5 episodes since last reflection).

#### Learning Cycle in ThinkEngine

When a reflection event is received, ThinkEngine:

1. Loads recent episodes (since last reflection)
2. Analyzes patterns:
   - Success/failure rates per task type
   - Repeated failure patterns
   - Time-to-completion trends
   - Common HITL escalation reasons
3. Produces insights
4. Stores insights (storage depends on memory module redesign)
5. Future think cycles can recall these insights

#### New ThinkEngine tool: `record_learning_insight`

```python
def record_learning_insight(
    category: str,     # "pattern" | "optimization" | "risk" | "capability_gap"
    insight: str,      # what was learned
    evidence: str,     # episode IDs or summary supporting this
    action: str,       # recommended action (may trigger self-mutation)
) -> str:
```

If insight.action suggests self-mutation (e.g., "add a new skill"), agent can follow up with self-mutation tools (which will trigger HITL).

### 8. Event Flow: Complete Picture

```
External World                    Daemon
  |                                 |
  |--[GitHub webhook]---> WebhookSensor ---> EventBus
  |--[file change]------> FileWatchSensor -> EventBus
  |                       SchedulerSensor -> EventBus (cron/interval)
  |                       InternalSensor --> EventBus (episode threshold)
  |                                          |
  |                                          v
  |                                      AgentLoop
  |                                    /    |     \
  |                                WAKE   THINK   ACT ---> REFLECT
  |                                         |       |         |
  |                                    ThinkEngine  Runtime   Episode recording
  |                                    (+ goals)    (tools)   Goal progress update
  |                                    (+ insights)           Learning trigger check
  |                                         |
  |                                    Self-mutation tools
  |                                         |
  |                                    HITL approval
  |                                         |
  |<--[Lark/WS notification]---  Hot reload if approved
```

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Sensor interface | Formal ABC | Type safety, clear contract |
| Webhook identifier | agent UUID | Uniqueness, no rename issues |
| PollSensor | Deferred | Not needed for initial version |
| Self-mutation HITL | Required | Human must approve all self-modifications |
| HITL content | Show proposed diff | Human needs to understand what changes |
| Permission mutation | Forbidden (hard-coded) | Security boundary, non-negotiable |
| User goals | Immutable | Source of truth, daemon only manages breakdown |
| Learning cycle threshold | Min 5 episodes | Avoid noise from insufficient data |
| Goal breakdown storage | Depends on memory redesign | Will adapt to new memory architecture |

## Out of Scope

- PollSensor implementation (future phase)
- Inter-agent communication (existing sub-agent + DAG is sufficient)
- Memory module internals (under separate redesign)
- Specific agent YAML examples for each sensor type (implementation detail)

## Risks

| Risk | Mitigation |
|---|---|
| Self-mutation tool bypasses permission check | Hard-coded rejection at tool level + integration test |
| WebhookSensor endpoint abuse | HMAC signature verification, rate limiting |
| Learning cycle produces bad insights | Insights are advisory, self-mutation still requires HITL |
| Hot reload race with active execution | Existing hot reload already handles this gracefully |
| Goal breakdown diverges from user intent | User goals always visible in context, HITL on mutations |

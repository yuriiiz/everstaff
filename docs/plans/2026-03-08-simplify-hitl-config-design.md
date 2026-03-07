# Simplify HITL Configuration — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove per-trigger `hitl_channels` and unreliable `hitl_mode: "always"` to simplify HITL configuration.

**Architecture:** Two independent simplifications — (1) flatten channel resolution from 3 levels to 2 (agent > global), (2) drop the unenforced `always` mode from the Literal type and tool.

**Tech Stack:** Python/Pydantic schemas, async daemon, React frontend

---

### Task 1: Remove `hitl_channels` from `TriggerConfig` schema

**Files:**
- Modify: `src/everstaff/schema/autonomy.py:22`

**Step 1: Remove the field**

In `src/everstaff/schema/autonomy.py`, remove line 22:

```python
# REMOVE this line from TriggerConfig:
    hitl_channels: list[HitlChannelRef] | None = None
```

The `HitlChannelRef` import and class stay — they're still used by `AgentSpec.hitl_channels`.

**Step 2: Run schema tests**

Run: `python -m pytest tests/test_schema/test_hitl_channel_ref.py -v`
Expected: 2 failures (`test_trigger_config_hitl_channels_default_none`, `test_trigger_config_hitl_channels_parsed`)

**Step 3: Fix trigger config tests**

- Modify: `tests/test_schema/test_hitl_channel_ref.py`

Delete `test_trigger_config_hitl_channels_default_none` (lines 15-18) and `test_trigger_config_hitl_channels_parsed` (lines 21-29). Keep `test_hitl_channel_ref_ref_only`, `test_hitl_channel_ref_with_overrides`, `test_agent_spec_hitl_channels_default_empty`, `test_agent_spec_hitl_channels_parsed`.

**Step 4: Run tests to verify**

Run: `python -m pytest tests/test_schema/test_hitl_channel_ref.py -v`
Expected: 4 PASS

**Step 5: Commit**

```bash
git add src/everstaff/schema/autonomy.py tests/test_schema/test_hitl_channel_ref.py
git commit -m "refactor(schema): remove hitl_channels from TriggerConfig"
```

---

### Task 2: Simplify `AgentLoop` channel resolution

**Files:**
- Modify: `src/everstaff/daemon/agent_loop.py:55-151`

**Step 1: Remove `agent_hitl_channels` param and simplify `_resolve_channels`**

In `AgentLoop.__init__` (line 68), remove the `agent_hitl_channels` parameter and its assignment (line 89).

In `_resolve_channels` (lines 110-151), replace the entire method with simplified logic that only uses agent-level `hitl_channels`:

```python
    def _resolve_channels(self, event: Any) -> Any:
        """Return a scoped ChannelManager for this event.

        Uses agent-level hitl_channels if configured, otherwise
        falls back to the default channel_manager.
        """
        from everstaff.channels.manager import ChannelManager

        if not self._agent_hitl_channels:
            return self._channel_manager  # fallback to global

        # Build scoped ChannelManager from refs + registry
        scoped = ChannelManager()
        for ref in self._agent_hitl_channels:
            channel = self._channel_registry.get(ref.ref)
            if channel is None:
                logger.warning(
                    "[Loop:%s] Channel ref '%s' not found in registry, skipping",
                    self._agent_name, ref.ref,
                )
                continue
            overrides = ref.overrides()
            if overrides:
                channel = _apply_channel_overrides(channel, overrides)
            scoped.register(channel)
        return scoped
```

Wait — since we removed the `agent_hitl_channels` **param**, we need a new way to pass agent-level channels. Rename the param to `hitl_channels` (cleaner now that there's only one level):

In `__init__` signature, replace:
```python
        agent_hitl_channels: list[Any] | None = None, # list[HitlChannelRef]
```
with:
```python
        hitl_channels: list[Any] | None = None,  # list[HitlChannelRef]
```

And in the body, replace:
```python
        self._agent_hitl_channels = agent_hitl_channels or []
```
with:
```python
        self._hitl_channels = hitl_channels or []
```

Update `_resolve_channels` to use `self._hitl_channels` instead of `self._agent_hitl_channels`.

**Step 2: Run agent loop tests**

Run: `python -m pytest tests/test_daemon/test_agent_loop.py -v`
Expected: 3 failures in channel resolution tests (they pass `agent_hitl_channels=`)

**Step 3: Update channel resolution tests**

- Modify: `tests/test_daemon/test_agent_loop.py:268-416`

Delete `test_loop_uses_trigger_hitl_channels` (lines 268-322) — tests per-trigger channels which no longer exist.

Rewrite `test_loop_falls_back_to_agent_hitl_channels` (lines 326-374) → rename to `test_loop_uses_agent_hitl_channels`:

```python
@pytest.mark.asyncio
async def test_loop_uses_agent_hitl_channels():
    """Agent-level hitl_channels → scoped ChannelManager passed to runtime."""
    from everstaff.schema.autonomy import HitlChannelRef

    bus = EventBus()
    bus.subscribe("test-agent")

    decision = Decision(action="execute", task_prompt="do work", reasoning="r", priority="normal")
    think = MockThinkEngine(decision)
    received_cm = []

    class _CapturingRuntime:
        async def run(self, prompt: str, **kw) -> str:
            return "done"

    def _factory(**kw):
        received_cm.append(kw.get("channel_manager"))
        return _CapturingRuntime()

    class _FakeChannel:
        async def send_request(self, *a): pass
        async def on_resolved(self, *a): pass
        async def start(self): pass
        async def stop(self): pass

    agent_ch = _FakeChannel()

    loop = AgentLoop(
        agent_name="test-agent",
        event_bus=bus,
        think_engine=think,
        runtime_factory=_factory,
        daemon_state_store=DaemonStateStore(InMemoryFileStore()),
        agent_uuid="test-uuid",
        tracer=NullTracer(),
        hitl_channels=[HitlChannelRef(ref="agent-ch")],
        channel_registry={"agent-ch": agent_ch},
    )

    await bus.publish(AgentEvent(source="cron", type="cron.daily", target_agent="test-agent"))
    await loop.run_once()

    scoped = received_cm[0]
    assert agent_ch in scoped._channels
```

Rewrite `test_loop_no_hitl_channels_passes_default_cm` (lines 378-416) — change `agent_hitl_channels=[]` to `hitl_channels=[]`:

```python
    loop = AgentLoop(
        ...
        hitl_channels=[],
        channel_registry={},
    )
```

**Step 4: Run tests to verify**

Run: `python -m pytest tests/test_daemon/test_agent_loop.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/everstaff/daemon/agent_loop.py tests/test_daemon/test_agent_loop.py
git commit -m "refactor(daemon): simplify AgentLoop channel resolution to agent-level only"
```

---

### Task 3: Update `AgentDaemon` to use new param name

**Files:**
- Modify: `src/everstaff/daemon/agent_daemon.py:238`

**Step 1: Rename kwarg**

Change line 238 from:
```python
            agent_hitl_channels=spec.hitl_channels,
```
to:
```python
            hitl_channels=spec.hitl_channels,
```

**Step 2: Update daemon test**

- Modify: `tests/test_daemon/test_agent_daemon.py:179`

Update docstring (line 179) — remove "agent_hitl_channels" reference. The test asserts `kw["channel_registry"]` and `kw["triggers"]` (lines 232-234) — these still work. But we should also verify the old `agent_hitl_channels` key is NOT present and the new `hitl_channels` key IS present. Add after line 234:

```python
    assert "agent_hitl_channels" not in kw
```

**Step 3: Run daemon tests**

Run: `python -m pytest tests/test_daemon/test_agent_daemon.py -v`
Expected: ALL PASS

**Step 4: Commit**

```bash
git add src/everstaff/daemon/agent_daemon.py tests/test_daemon/test_agent_daemon.py
git commit -m "refactor(daemon): rename agent_hitl_channels param to hitl_channels"
```

---

### Task 4: Remove `hitl_mode: "always"`

**Files:**
- Modify: `src/everstaff/schema/agent_spec.py:96-101`
- Modify: `src/everstaff/tools/hitl_tool.py:13,131-147`

**Step 1: Update schema**

In `src/everstaff/schema/agent_spec.py`, change lines 96-101:

```python
    # HITL — controls when the request_human_input tool is registered
    # "on_request" = full HITL (blocking + notify), agent decides when to ask
    # "notify"     = notify-only (non-blocking, fire-and-forget)
    # "never"      = tool not registered
    hitl_mode: Literal["on_request", "notify", "never"] = "on_request"
```

**Step 2: Update hitl_tool.py**

In `src/everstaff/tools/hitl_tool.py`, change line 13:
```python
_VALID_MODES = ("on_request", "notify")
```

Remove the `always` branch in `get_prompt_injection()` (lines 131-147):
```python
        if self._mode == "always":
            return (
                "## Supervised Execution Mode\n\n"
                ...
                "- You may use `notify` type for status updates without pausing"
            )
```

**Step 3: Run tests**

Run: `python -m pytest tests/test_workflow/test_workflow_spec.py tests/test_builder/ -v`
Expected: Possible failure in `test_agent_spec_hitl_mode_never` if Pydantic rejects `"always"` elsewhere — but we only need `"never"` to work.

**Step 4: Fix workflow spec test if needed**

- Modify: `tests/test_workflow/test_workflow_spec.py:233-236`

The test `test_agent_spec_hitl_mode_never` uses `hitl_mode="never"` which is still valid. No change needed. But verify no test uses `hitl_mode="always"`.

Run: `python -m pytest tests/ -v -k hitl_mode`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/everstaff/schema/agent_spec.py src/everstaff/tools/hitl_tool.py
git commit -m "refactor(hitl): remove unreliable hitl_mode 'always'"
```

---

### Task 5: Update frontend

**Files:**
- Modify: `web/src/pages/AgentStore.jsx`

**Step 1: Remove `"always"` option from hitl_mode selector**

At line 1143, remove:
```javascript
                                                                    { value: 'always', label: 'Always', desc: 'Ask every turn' },
```

**Step 2: Remove per-trigger HITL channels UI**

Remove the entire trigger HITL channels block (lines 1554-1593):
```jsx
                                                                    <div style={{ marginTop: '12px' }}>
                                                                        <div style={{ display: 'flex', justifyContent: 'space-between', ... }}>
                                                                            <label ...>TRIGGER HITL CHANNELS</label>
                                                                            ...
                                                                        </div>
                                                                        ...
                                                                    </div>
```

**Step 3: Simplify agent-level `availableRefs`**

At line 1185, simplify the `availableRefs` prop — remove the trigger flatMap since triggers no longer have hitl_channels:

From:
```javascript
availableRefs={[...new Set([...globalHitlChannels, ...(selectedAgent.autonomy?.triggers || []).flatMap(t => (t.hitl_channels || []).map(c => c.ref))])]}
```
To:
```javascript
availableRefs={globalHitlChannels}
```

**Step 4: Commit**

```bash
git add web/src/pages/AgentStore.jsx
git commit -m "refactor(web): remove trigger hitl_channels UI and 'always' hitl_mode option"
```

---

### Task 6: Update docs

**Files:**
- Modify: `README.md` (if `hitl_mode: always` mentioned)
- Modify: `docs/usage.md`, `docs/getting-started.md` (if applicable)

**Step 1: Check and update docs**

Search for any `always` references in docs related to hitl_mode. The README line 101 shows `hitl_mode: on_request` which is fine. Update if any doc mentions `always` as a valid option.

**Step 2: Commit**

```bash
git add README.md docs/
git commit -m "docs: update hitl_mode options, remove 'always'"
```

---

### Task 7: Final verification

**Step 1: Run full test suite**

Run: `python -m pytest tests/ -v --tb=short`
Expected: ALL PASS

**Step 2: Verify no stale references**

Run: `grep -r "hitl_channels" src/everstaff/schema/autonomy.py` — should find nothing
Run: `grep -r "agent_hitl_channels" src/` — should find nothing
Run: `grep -r '"always"' src/everstaff/tools/hitl_tool.py src/everstaff/schema/agent_spec.py` — should find nothing

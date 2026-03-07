# Daemon Autonomous Capabilities Upgrade - Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Upgrade the daemon from a schedule-only reactor to a fully autonomous agent that discovers needs via multiple signal sources, manages long-term goals, learns from execution history, and evolves its own capabilities (except permissions) through HITL-gated self-mutation.

**Architecture:** Formalize the Sensor ABC, add WebhookSensor/FileWatchSensor/InternalSensor implementations, extend TriggerConfig schema, add goal breakdown tools to ThinkEngine, add self-mutation tools with HITL guard, and wire a closed-loop learning cycle triggered by InternalSensor.

**Tech Stack:** Python 3.11+, asyncio, FastAPI, APScheduler v3, watchfiles, Pydantic v2, pytest + pytest-asyncio

---

## Task 1: Sensor ABC

Define the formal abstract base class that all sensors must implement.

**Files:**
- Create: `src/everstaff/daemon/sensors/base.py`
- Test: `tests/test_daemon/test_sensor_abc.py`

**Step 1: Write the failing test**

```python
# tests/test_daemon/test_sensor_abc.py
"""Tests for Sensor ABC contract."""
import pytest
from everstaff.daemon.sensors.base import Sensor


def test_sensor_is_abstract():
    """Cannot instantiate Sensor directly."""
    with pytest.raises(TypeError):
        Sensor()


def test_sensor_subclass_must_implement_start_and_stop():
    """Subclass missing methods raises TypeError on instantiation."""

    class BadSensor(Sensor):
        pass

    with pytest.raises(TypeError):
        BadSensor()


def test_sensor_subclass_with_methods_instantiates():
    """Subclass implementing both methods instantiates fine."""

    class GoodSensor(Sensor):
        async def start(self, event_bus):
            pass

        async def stop(self):
            pass

    s = GoodSensor()
    assert isinstance(s, Sensor)
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/yuriiiz/Projects/everstaff && python -m pytest tests/test_daemon/test_sensor_abc.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'everstaff.daemon.sensors.base'`

**Step 3: Write minimal implementation**

```python
# src/everstaff/daemon/sensors/base.py
"""Sensor ABC — formal interface for all daemon sensors."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from everstaff.daemon.event_bus import EventBus


class Sensor(ABC):
    """Base class for all sensors that feed events into the daemon EventBus."""

    @abstractmethod
    async def start(self, event_bus: "EventBus") -> None:
        """Start producing events and publishing them to *event_bus*."""

    @abstractmethod
    async def stop(self) -> None:
        """Stop producing events and release resources."""
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/yuriiiz/Projects/everstaff && python -m pytest tests/test_daemon/test_sensor_abc.py -v`
Expected: PASS (3 tests)

**Step 5: Commit**

```bash
git add src/everstaff/daemon/sensors/base.py tests/test_daemon/test_sensor_abc.py
git commit -m "feat(daemon): add Sensor ABC for formal sensor interface"
```

---

## Task 2: Refactor SchedulerSensor to extend Sensor ABC

**Files:**
- Modify: `src/everstaff/daemon/sensors/scheduler.py`
- Test: `tests/test_daemon/test_scheduler_sensor.py` (existing — verify still passes)

**Step 1: Write a failing test that verifies SchedulerSensor is a Sensor**

Add to `tests/test_daemon/test_scheduler_sensor.py`:

```python
from everstaff.daemon.sensors.base import Sensor
from everstaff.daemon.sensors.scheduler import SchedulerSensor


def test_scheduler_sensor_is_sensor_subclass():
    sensor = SchedulerSensor(triggers=[], agent_name="test")
    assert isinstance(sensor, Sensor)
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/yuriiiz/Projects/everstaff && python -m pytest tests/test_daemon/test_scheduler_sensor.py::test_scheduler_sensor_is_sensor_subclass -v`
Expected: FAIL — `AssertionError` (SchedulerSensor doesn't extend Sensor yet)

**Step 3: Modify SchedulerSensor**

In `src/everstaff/daemon/sensors/scheduler.py`, change:

```python
# Before (line 28):
class SchedulerSensor:

# After:
from everstaff.daemon.sensors.base import Sensor

class SchedulerSensor(Sensor):
```

**Step 4: Run full test suite for scheduler sensor**

Run: `cd /Users/yuriiiz/Projects/everstaff && python -m pytest tests/test_daemon/test_scheduler_sensor.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/everstaff/daemon/sensors/scheduler.py tests/test_daemon/test_scheduler_sensor.py
git commit -m "refactor(daemon): SchedulerSensor extends Sensor ABC"
```

---

## Task 3: Extend TriggerConfig schema for new trigger types

**Files:**
- Modify: `src/everstaff/schema/autonomy.py`
- Test: `tests/test_daemon/test_trigger_schema.py`

**Step 1: Write failing tests**

```python
# tests/test_daemon/test_trigger_schema.py
"""Tests for extended TriggerConfig schema."""
import pytest
from everstaff.schema.autonomy import TriggerConfig


def test_webhook_trigger():
    t = TriggerConfig(id="gh-pr", type="webhook", task="handle PR")
    assert t.type == "webhook"
    assert t.task == "handle PR"


def test_file_watch_trigger():
    t = TriggerConfig(
        id="cfg-watch",
        type="file_watch",
        task="config changed",
        watch_paths=["config/", "agents/"],
    )
    assert t.type == "file_watch"
    assert t.watch_paths == ["config/", "agents/"]


def test_internal_trigger():
    t = TriggerConfig(
        id="self-reflect",
        type="internal",
        task="analyze episodes",
        condition="episode_count",
        threshold=5,
    )
    assert t.type == "internal"
    assert t.condition == "episode_count"
    assert t.threshold == 5


def test_internal_trigger_default_threshold():
    t = TriggerConfig(id="x", type="internal", condition="episode_count")
    assert t.threshold == 5


def test_cron_trigger_unchanged():
    t = TriggerConfig(id="daily", type="cron", schedule="0 9 * * *", task="check")
    assert t.schedule == "0 9 * * *"
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/yuriiiz/Projects/everstaff && python -m pytest tests/test_daemon/test_trigger_schema.py -v`
Expected: FAIL — `watch_paths`, `condition`, `threshold` are not fields on TriggerConfig

**Step 3: Modify TriggerConfig**

In `src/everstaff/schema/autonomy.py`, extend TriggerConfig (currently around line 15-22):

```python
class TriggerConfig(BaseModel):
    id: str
    type: str  # "cron" | "interval" | "webhook" | "file_watch" | "internal"
    schedule: str = ""          # cron expression (for type="cron")
    every: int = 0              # seconds (for type="interval")
    task: str = ""              # task description for ThinkEngine
    hitl_channels: list[HitlChannelRef] | None = None
    # webhook — no extra fields needed, uses agent UUID for endpoint
    # file_watch
    watch_paths: list[str] = Field(default_factory=list)
    # internal
    condition: str = ""         # "episode_count" | "goal_stale" | "error_rate"
    threshold: int = 5          # minimum threshold before firing
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/yuriiiz/Projects/everstaff && python -m pytest tests/test_daemon/test_trigger_schema.py -v`
Expected: ALL PASS

**Step 5: Run existing daemon tests to confirm no regressions**

Run: `cd /Users/yuriiiz/Projects/everstaff && python -m pytest tests/test_daemon/ -v`
Expected: ALL PASS

**Step 6: Commit**

```bash
git add src/everstaff/schema/autonomy.py tests/test_daemon/test_trigger_schema.py
git commit -m "feat(daemon): extend TriggerConfig for webhook, file_watch, internal triggers"
```

---

## Task 4: WebhookSensor

**Files:**
- Create: `src/everstaff/daemon/sensors/webhook.py`
- Modify: `src/everstaff/api/daemon.py` (add webhook route)
- Test: `tests/test_daemon/test_webhook_sensor.py`

**Step 1: Write failing tests**

```python
# tests/test_daemon/test_webhook_sensor.py
"""Tests for WebhookSensor."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from everstaff.daemon.sensors.base import Sensor
from everstaff.daemon.sensors.webhook import WebhookSensor
from everstaff.daemon.event_bus import EventBus
from everstaff.schema.autonomy import TriggerConfig


@pytest.fixture
def bus():
    b = EventBus()
    b.subscribe("test-agent")
    return b


@pytest.fixture
def webhook_triggers():
    return [
        TriggerConfig(id="gh-pr", type="webhook", task="handle PR event"),
    ]


def test_webhook_sensor_is_sensor():
    ws = WebhookSensor(
        triggers=[], agent_name="a", agent_uuid="uuid-1", app=MagicMock(),
    )
    assert isinstance(ws, Sensor)


@pytest.mark.asyncio
async def test_webhook_sensor_registers_route(bus, webhook_triggers):
    app = MagicMock()
    app.routes = []
    ws = WebhookSensor(
        triggers=webhook_triggers,
        agent_name="test-agent",
        agent_uuid="uuid-123",
        app=app,
    )
    await ws.start(bus)
    # Should have called app.add_api_route
    app.add_api_route.assert_called_once()
    call_args = app.add_api_route.call_args
    assert "uuid-123" in call_args[0][0] or "uuid-123" in str(call_args)
    await ws.stop()


@pytest.mark.asyncio
async def test_webhook_sensor_publishes_event(bus, webhook_triggers):
    app = MagicMock()
    ws = WebhookSensor(
        triggers=webhook_triggers,
        agent_name="test-agent",
        agent_uuid="uuid-123",
        app=app,
    )
    await ws.start(bus)

    # Simulate incoming webhook
    await ws.handle_webhook(trigger_id="gh-pr", payload={"action": "opened"})

    event = await asyncio.wait_for(bus.wait_for("test-agent", timeout=1), timeout=2)
    assert event is not None
    assert event.source == "webhook"
    assert event.type == "webhook.gh-pr"
    assert event.payload["action"] == "opened"
    assert event.target_agent == "test-agent"
    await ws.stop()
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/yuriiiz/Projects/everstaff && python -m pytest tests/test_daemon/test_webhook_sensor.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Write implementation**

```python
# src/everstaff/daemon/sensors/webhook.py
"""WebhookSensor — receives external HTTP push events via FastAPI endpoint."""
from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from everstaff.daemon.sensors.base import Sensor

if TYPE_CHECKING:
    from everstaff.daemon.event_bus import EventBus
    from everstaff.schema.autonomy import TriggerConfig

logger = logging.getLogger(__name__)


class WebhookSensor(Sensor):
    """Registers ``POST /api/daemon/webhook/{agent_uuid}`` on the FastAPI app.

    Incoming requests are converted to AgentEvents and published to EventBus.
    """

    def __init__(
        self,
        triggers: list[TriggerConfig],
        agent_name: str,
        agent_uuid: str,
        app: Any,
    ) -> None:
        self._triggers = {t.id: t for t in triggers if t.type == "webhook"}
        self._agent_name = agent_name
        self._agent_uuid = agent_uuid
        self._app = app
        self._bus: EventBus | None = None
        self._route_path: str | None = None

    async def start(self, event_bus: EventBus) -> None:
        if not self._triggers:
            return
        self._bus = event_bus
        self._route_path = f"/api/daemon/webhook/{self._agent_uuid}"

        async def _endpoint(request: Any) -> dict:
            from starlette.requests import Request

            body: dict = {}
            if isinstance(request, Request):
                body = await request.json()
            trigger_id = body.pop("trigger_id", None)
            if trigger_id and trigger_id in self._triggers:
                await self.handle_webhook(trigger_id=trigger_id, payload=body)
            elif len(self._triggers) == 1:
                tid = next(iter(self._triggers))
                await self.handle_webhook(trigger_id=tid, payload=body)
            else:
                await self.handle_webhook(trigger_id="unknown", payload=body)
            return {"status": "accepted"}

        self._app.add_api_route(
            self._route_path,
            _endpoint,
            methods=["POST"],
            name=f"webhook_{self._agent_uuid}",
        )
        logger.info(
            "[WebhookSensor:%s] Registered endpoint %s for %d trigger(s)",
            self._agent_name, self._route_path, len(self._triggers),
        )

    async def handle_webhook(self, *, trigger_id: str, payload: dict) -> None:
        """Publish an AgentEvent from an incoming webhook payload."""
        from everstaff.protocols import AgentEvent

        trigger = self._triggers.get(trigger_id)
        task = trigger.task if trigger else ""

        event = AgentEvent(
            source="webhook",
            type=f"webhook.{trigger_id}",
            payload={**payload, "task": task, "trigger_id": trigger_id},
            target_agent=self._agent_name,
        )
        if self._bus:
            await self._bus.publish(event)
            logger.info(
                "[WebhookSensor:%s] Published event for trigger '%s'",
                self._agent_name, trigger_id,
            )

    async def stop(self) -> None:
        # FastAPI doesn't support dynamic route removal cleanly;
        # routes become inactive when sensor is garbage-collected.
        self._bus = None
        logger.info("[WebhookSensor:%s] Stopped", self._agent_name)
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/yuriiiz/Projects/everstaff && python -m pytest tests/test_daemon/test_webhook_sensor.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/everstaff/daemon/sensors/webhook.py tests/test_daemon/test_webhook_sensor.py
git commit -m "feat(daemon): add WebhookSensor for external HTTP event intake"
```

---

## Task 5: FileWatchSensor

**Files:**
- Create: `src/everstaff/daemon/sensors/file_watch.py`
- Test: `tests/test_daemon/test_file_watch_sensor.py`

**Step 1: Add `watchfiles` dependency**

Run: `cd /Users/yuriiiz/Projects/everstaff && uv add watchfiles`

**Step 2: Write failing tests**

```python
# tests/test_daemon/test_file_watch_sensor.py
"""Tests for FileWatchSensor."""
import asyncio
import os
import tempfile
import pytest

from everstaff.daemon.sensors.base import Sensor
from everstaff.daemon.sensors.file_watch import FileWatchSensor
from everstaff.daemon.event_bus import EventBus
from everstaff.schema.autonomy import TriggerConfig


@pytest.fixture
def bus():
    b = EventBus()
    b.subscribe("watcher")
    return b


def test_file_watch_sensor_is_sensor():
    sensor = FileWatchSensor(triggers=[], agent_name="w")
    assert isinstance(sensor, Sensor)


@pytest.mark.asyncio
async def test_file_watch_detects_change(bus, tmp_path):
    watched = tmp_path / "config"
    watched.mkdir()

    trigger = TriggerConfig(
        id="cfg-watch",
        type="file_watch",
        task="config changed",
        watch_paths=[str(watched)],
    )
    sensor = FileWatchSensor(triggers=[trigger], agent_name="watcher")
    await sensor.start(bus)

    # Give watcher time to start
    await asyncio.sleep(0.3)

    # Create a file to trigger watch
    (watched / "test.yaml").write_text("key: value")

    # Wait for event
    event = await asyncio.wait_for(bus.wait_for("watcher", timeout=5), timeout=6)
    assert event is not None
    assert event.source == "file_watch"
    assert event.type == "file_watch.cfg-watch"
    assert event.target_agent == "watcher"

    await sensor.stop()
```

**Step 3: Run test to verify it fails**

Run: `cd /Users/yuriiiz/Projects/everstaff && python -m pytest tests/test_daemon/test_file_watch_sensor.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 4: Write implementation**

```python
# src/everstaff/daemon/sensors/file_watch.py
"""FileWatchSensor — monitors file/directory changes using watchfiles."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from everstaff.daemon.sensors.base import Sensor

if TYPE_CHECKING:
    from everstaff.daemon.event_bus import EventBus
    from everstaff.schema.autonomy import TriggerConfig

logger = logging.getLogger(__name__)

_CHANGE_LABELS = {1: "added", 2: "modified", 3: "deleted"}


class FileWatchSensor(Sensor):
    """Watches file paths and publishes AgentEvents on changes."""

    def __init__(self, triggers: list[TriggerConfig], agent_name: str) -> None:
        self._triggers = [t for t in triggers if t.type == "file_watch"]
        self._agent_name = agent_name
        self._bus: EventBus | None = None
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

    async def start(self, event_bus: EventBus) -> None:
        if not self._triggers:
            return
        self._bus = event_bus
        self._stop_event.clear()
        self._task = asyncio.create_task(self._watch_loop(), name=f"file-watch-{self._agent_name}")
        logger.info("[FileWatchSensor:%s] Started watching %d trigger(s)", self._agent_name, len(self._triggers))

    async def _watch_loop(self) -> None:
        from watchfiles import awatch

        # Collect all paths from all file_watch triggers
        path_to_trigger: dict[str, TriggerConfig] = {}
        all_paths: list[Path] = []
        for trigger in self._triggers:
            for p in trigger.watch_paths:
                resolved = Path(p).resolve()
                path_to_trigger[str(resolved)] = trigger
                all_paths.append(resolved)

        try:
            async for changes in awatch(*all_paths, stop_event=self._stop_event):
                for change_type, changed_path in changes:
                    label = _CHANGE_LABELS.get(change_type, "unknown")
                    # Find which trigger this path belongs to
                    trigger = self._find_trigger(changed_path, path_to_trigger)
                    if trigger and self._bus:
                        from everstaff.protocols import AgentEvent

                        event = AgentEvent(
                            source="file_watch",
                            type=f"file_watch.{trigger.id}",
                            payload={
                                "task": trigger.task,
                                "trigger_id": trigger.id,
                                "changed_path": changed_path,
                                "change_type": label,
                            },
                            target_agent=self._agent_name,
                        )
                        await self._bus.publish(event)
                        logger.info(
                            "[FileWatchSensor:%s] %s: %s (%s)",
                            self._agent_name, trigger.id, changed_path, label,
                        )
        except asyncio.CancelledError:
            pass

    def _find_trigger(self, changed_path: str, path_to_trigger: dict[str, TriggerConfig]) -> TriggerConfig | None:
        changed = Path(changed_path).resolve()
        for watched_str, trigger in path_to_trigger.items():
            watched = Path(watched_str)
            if changed == watched or watched in changed.parents:
                return trigger
        return None

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        self._bus = None
        logger.info("[FileWatchSensor:%s] Stopped", self._agent_name)
```

**Step 5: Run test to verify it passes**

Run: `cd /Users/yuriiiz/Projects/everstaff && python -m pytest tests/test_daemon/test_file_watch_sensor.py -v`
Expected: ALL PASS

**Step 6: Commit**

```bash
git add src/everstaff/daemon/sensors/file_watch.py tests/test_daemon/test_file_watch_sensor.py
git commit -m "feat(daemon): add FileWatchSensor for file/directory change detection"
```

---

## Task 6: InternalSensor

**Files:**
- Create: `src/everstaff/daemon/sensors/internal.py`
- Test: `tests/test_daemon/test_internal_sensor.py`

**Step 1: Write failing tests**

```python
# tests/test_daemon/test_internal_sensor.py
"""Tests for InternalSensor."""
import asyncio
import pytest

from everstaff.daemon.sensors.base import Sensor
from everstaff.daemon.sensors.internal import InternalSensor
from everstaff.daemon.event_bus import EventBus
from everstaff.schema.autonomy import TriggerConfig


@pytest.fixture
def bus():
    b = EventBus()
    b.subscribe("reflector")
    return b


def test_internal_sensor_is_sensor():
    sensor = InternalSensor(triggers=[], agent_name="r")
    assert isinstance(sensor, Sensor)


@pytest.mark.asyncio
async def test_episode_count_fires_at_threshold(bus):
    trigger = TriggerConfig(
        id="self-reflect",
        type="internal",
        condition="episode_count",
        threshold=3,
        task="analyze episodes",
    )
    sensor = InternalSensor(triggers=[trigger], agent_name="reflector")
    await sensor.start(bus)

    # Notify fewer than threshold — no event
    for _ in range(2):
        sensor.notify_episode()
    # Should be empty
    event = await bus.wait_for("reflector", timeout=0.1)
    assert event is None

    # One more crosses threshold
    sensor.notify_episode()
    event = await asyncio.wait_for(bus.wait_for("reflector", timeout=1), timeout=2)
    assert event is not None
    assert event.source == "internal"
    assert event.type == "internal.self-reflect"
    assert event.payload["condition"] == "episode_count"

    await sensor.stop()


@pytest.mark.asyncio
async def test_counter_resets_after_firing(bus):
    trigger = TriggerConfig(
        id="reflect", type="internal", condition="episode_count",
        threshold=2, task="reflect",
    )
    sensor = InternalSensor(triggers=[trigger], agent_name="reflector")
    await sensor.start(bus)

    # Fire once
    sensor.notify_episode()
    sensor.notify_episode()
    event = await asyncio.wait_for(bus.wait_for("reflector", timeout=1), timeout=2)
    assert event is not None

    # Counter should have reset — one more should not fire
    sensor.notify_episode()
    event = await bus.wait_for("reflector", timeout=0.1)
    assert event is None

    await sensor.stop()
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/yuriiiz/Projects/everstaff && python -m pytest tests/test_daemon/test_internal_sensor.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Write implementation**

```python
# src/everstaff/daemon/sensors/internal.py
"""InternalSensor — monitors daemon-internal state and emits events at thresholds."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from everstaff.daemon.sensors.base import Sensor

if TYPE_CHECKING:
    from everstaff.daemon.event_bus import EventBus
    from everstaff.schema.autonomy import TriggerConfig

logger = logging.getLogger(__name__)


class InternalSensor(Sensor):
    """Counts internal events (episodes, errors) and fires when thresholds are met."""

    def __init__(self, triggers: list[TriggerConfig], agent_name: str) -> None:
        self._triggers = [t for t in triggers if t.type == "internal"]
        self._agent_name = agent_name
        self._bus: EventBus | None = None
        self._episode_count: int = 0

    async def start(self, event_bus: EventBus) -> None:
        self._bus = event_bus
        self._episode_count = 0
        logger.info(
            "[InternalSensor:%s] Started with %d trigger(s)",
            self._agent_name, len(self._triggers),
        )

    def notify_episode(self) -> None:
        """Called by AgentLoop after each episode is recorded."""
        self._episode_count += 1
        for trigger in self._triggers:
            if trigger.condition == "episode_count" and self._episode_count >= trigger.threshold:
                self._episode_count = 0
                self._fire(trigger)

    def _fire(self, trigger: TriggerConfig) -> None:
        if not self._bus:
            return
        import asyncio
        from everstaff.protocols import AgentEvent

        event = AgentEvent(
            source="internal",
            type=f"internal.{trigger.id}",
            payload={
                "task": trigger.task,
                "trigger_id": trigger.id,
                "condition": trigger.condition,
            },
            target_agent=self._agent_name,
        )
        # Schedule coroutine on the running event loop
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._bus.publish(event))
        except RuntimeError:
            logger.warning("[InternalSensor:%s] No running event loop, skipping fire", self._agent_name)

        logger.info(
            "[InternalSensor:%s] Fired trigger '%s' (condition=%s)",
            self._agent_name, trigger.id, trigger.condition,
        )

    async def stop(self) -> None:
        self._bus = None
        self._episode_count = 0
        logger.info("[InternalSensor:%s] Stopped", self._agent_name)
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/yuriiiz/Projects/everstaff && python -m pytest tests/test_daemon/test_internal_sensor.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/everstaff/daemon/sensors/internal.py tests/test_daemon/test_internal_sensor.py
git commit -m "feat(daemon): add InternalSensor for episode-count-based learning triggers"
```

---

## Task 7: Wire new sensors into AgentDaemon

**Files:**
- Modify: `src/everstaff/daemon/agent_daemon.py` (lines 153-211, `_start_agent`)
- Modify: `src/everstaff/daemon/agent_loop.py` (reflect phase, ~lines 241-271)
- Test: `tests/test_daemon/test_agent_daemon.py` (add new test cases)

**Step 1: Write failing tests**

Add to `tests/test_daemon/test_agent_daemon.py`:

```python
@pytest.mark.asyncio
async def test_daemon_creates_webhook_sensor(tmp_path):
    """Daemon creates WebhookSensor for agents with webhook triggers."""
    _write_agent_yaml(tmp_path / "webhook_agent.yaml", {
        "agent_name": "webhook-bot",
        "uuid": "uuid-webhook-1",
        "autonomy": {
            "enabled": True,
            "triggers": [
                {"id": "gh-pr", "type": "webhook", "task": "handle PR"},
            ],
        },
    })
    daemon = AgentDaemon(
        agents_dir=str(tmp_path),
        memory=InMemoryStore(),
        tracer=NullTracer(),
        llm_factory=lambda **kw: None,
        runtime_factory=lambda **kw: None,
        app=MagicMock(),  # FastAPI app mock
    )
    await daemon.start()
    assert daemon.is_running
    # Verify sensor_manager has sensors registered
    assert len(daemon.sensor_manager._sensors) > 0
    await daemon.stop()


@pytest.mark.asyncio
async def test_daemon_creates_internal_sensor(tmp_path):
    """Daemon creates InternalSensor for agents with internal triggers."""
    _write_agent_yaml(tmp_path / "reflect_agent.yaml", {
        "agent_name": "reflector",
        "autonomy": {
            "enabled": True,
            "triggers": [
                {"id": "reflect", "type": "internal", "condition": "episode_count", "threshold": 5, "task": "reflect"},
                {"id": "daily", "type": "cron", "schedule": "0 9 * * *", "task": "check"},
            ],
        },
    })
    daemon = AgentDaemon(
        agents_dir=str(tmp_path),
        memory=InMemoryStore(),
        tracer=NullTracer(),
        llm_factory=lambda **kw: None,
        runtime_factory=lambda **kw: None,
    )
    await daemon.start()
    assert daemon.is_running
    await daemon.stop()
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/yuriiiz/Projects/everstaff && python -m pytest tests/test_daemon/test_agent_daemon.py::test_daemon_creates_webhook_sensor -v`
Expected: FAIL — `app` kwarg not accepted / sensor types not handled

**Step 3: Modify AgentDaemon._start_agent**

In `src/everstaff/daemon/agent_daemon.py`, update `_start_agent` (line ~153):

1. Accept optional `app` in `__init__` and store as `self._app`
2. In `_start_agent`, after creating SchedulerSensor, also create:
   - `WebhookSensor` if any trigger has `type="webhook"` and `self._app` is not None
   - `FileWatchSensor` if any trigger has `type="file_watch"`
   - `InternalSensor` if any trigger has `type="internal"`, store reference on loop for reflect phase

**Step 4: Wire InternalSensor.notify_episode into AgentLoop reflect phase**

In `src/everstaff/daemon/agent_loop.py`:
- Accept optional `internal_sensor: InternalSensor | None` in `__init__`
- In reflect phase (after `episode_append`), call `self._internal_sensor.notify_episode()` if set

**Step 5: Run tests**

Run: `cd /Users/yuriiiz/Projects/everstaff && python -m pytest tests/test_daemon/ -v`
Expected: ALL PASS

**Step 6: Commit**

```bash
git add src/everstaff/daemon/agent_daemon.py src/everstaff/daemon/agent_loop.py tests/test_daemon/test_agent_daemon.py
git commit -m "feat(daemon): wire WebhookSensor, FileWatchSensor, InternalSensor into daemon lifecycle"
```

---

## Task 8: Goal Breakdown — ThinkEngine tools

**Files:**
- Modify: `src/everstaff/daemon/think_engine.py` (add tools to THINK_TOOLS)
- Create: `src/everstaff/daemon/goals.py` (GoalBreakdown model + storage)
- Test: `tests/test_daemon/test_goals.py`

**Step 1: Write failing tests**

```python
# tests/test_daemon/test_goals.py
"""Tests for goal breakdown management."""
import pytest
from everstaff.daemon.goals import GoalBreakdown, SubGoal


def test_create_empty_breakdown():
    gb = GoalBreakdown(goal_id="g1")
    assert gb.goal_id == "g1"
    assert gb.sub_goals == []


def test_add_sub_goals():
    gb = GoalBreakdown(goal_id="g1")
    gb.sub_goals.append(SubGoal(description="step 1", acceptance_criteria="done when X"))
    assert len(gb.sub_goals) == 1
    assert gb.sub_goals[0].status == "pending"


def test_update_sub_goal_progress():
    gb = GoalBreakdown(goal_id="g1", sub_goals=[
        SubGoal(description="step 1"),
        SubGoal(description="step 2"),
    ])
    gb.sub_goals[0].status = "completed"
    gb.sub_goals[0].progress_note = "finished successfully"
    assert gb.sub_goals[0].status == "completed"


def test_completion_ratio():
    gb = GoalBreakdown(goal_id="g1", sub_goals=[
        SubGoal(description="a", status="completed"),
        SubGoal(description="b", status="in_progress"),
        SubGoal(description="c", status="pending"),
    ])
    assert gb.completion_ratio == pytest.approx(1 / 3)


def test_serialization_roundtrip():
    gb = GoalBreakdown(goal_id="g1", sub_goals=[
        SubGoal(description="step 1", status="completed"),
    ])
    data = gb.model_dump()
    gb2 = GoalBreakdown.model_validate(data)
    assert gb2.goal_id == gb.goal_id
    assert len(gb2.sub_goals) == 1
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/yuriiiz/Projects/everstaff && python -m pytest tests/test_daemon/test_goals.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Write GoalBreakdown model**

```python
# src/everstaff/daemon/goals.py
"""Goal breakdown models for daemon long-term goal management."""
from __future__ import annotations

from pydantic import BaseModel, Field


class SubGoal(BaseModel):
    description: str
    acceptance_criteria: str = ""
    status: str = "pending"  # "pending" | "in_progress" | "completed" | "blocked"
    progress_note: str = ""


class GoalBreakdown(BaseModel):
    """Daemon-maintained breakdown of a user-defined GoalConfig."""

    goal_id: str
    sub_goals: list[SubGoal] = Field(default_factory=list)

    @property
    def completion_ratio(self) -> float:
        if not self.sub_goals:
            return 0.0
        completed = sum(1 for sg in self.sub_goals if sg.status == "completed")
        return completed / len(self.sub_goals)
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/yuriiiz/Projects/everstaff && python -m pytest tests/test_daemon/test_goals.py -v`
Expected: ALL PASS

**Step 5: Add goal tools to ThinkEngine THINK_TOOLS**

In `src/everstaff/daemon/think_engine.py`, add two new tool definitions to `THINK_TOOLS` (after line ~96):

```python
ToolDefinition(
    name="break_down_goal",
    description="Break a user-defined goal into actionable sub-goals. The user's original goal is preserved and immutable.",
    parameters={
        "type": "object",
        "properties": {
            "goal_id": {"type": "string", "description": "The GoalConfig id to break down"},
            "sub_goals": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "description": {"type": "string"},
                        "acceptance_criteria": {"type": "string"},
                    },
                    "required": ["description"],
                },
                "description": "List of sub-goals to create",
            },
        },
        "required": ["goal_id", "sub_goals"],
    },
),
ToolDefinition(
    name="update_goal_progress",
    description="Update the status of a daemon-maintained sub-goal.",
    parameters={
        "type": "object",
        "properties": {
            "goal_id": {"type": "string"},
            "sub_goal_index": {"type": "integer", "description": "0-based index of the sub-goal"},
            "status": {"type": "string", "enum": ["pending", "in_progress", "completed", "blocked"]},
            "progress_note": {"type": "string"},
        },
        "required": ["goal_id", "sub_goal_index", "status"],
    },
),
```

Handle these tools in the think loop (alongside `recall_semantic_detail` and `recall_recent_episodes`). Store/load GoalBreakdown via working memory's `goals_breakdown` field (dict[goal_id, GoalBreakdown.model_dump()]).

**Step 6: Write test for ThinkEngine goal tool handling**

Add to `tests/test_daemon/test_think_engine.py`:

```python
@pytest.mark.asyncio
async def test_think_engine_break_down_goal(think_engine, mock_llm):
    """ThinkEngine handles break_down_goal tool call."""
    mock_llm.set_responses([
        # First call: break_down_goal
        LLMResponse(tool_calls=[ToolCall(
            id="tc1", name="break_down_goal",
            arguments={"goal_id": "g1", "sub_goals": [{"description": "step 1"}]},
        )]),
        # Second call: make_decision
        LLMResponse(tool_calls=[ToolCall(
            id="tc2", name="make_decision",
            arguments={"action": "execute", "reasoning": "goal broken down", "task_prompt": "do step 1"},
        )]),
    ])
    decision = await think_engine.think(
        agent_name="test", trigger=make_event(),
        pending_events=[], autonomy_goals=[GoalConfig(id="g1", description="big goal")],
        parent_session_id="ps1",
    )
    assert decision.action == "execute"
```

**Step 7: Run tests**

Run: `cd /Users/yuriiiz/Projects/everstaff && python -m pytest tests/test_daemon/test_goals.py tests/test_daemon/test_think_engine.py -v`
Expected: ALL PASS

**Step 8: Commit**

```bash
git add src/everstaff/daemon/goals.py src/everstaff/daemon/think_engine.py tests/test_daemon/test_goals.py tests/test_daemon/test_think_engine.py
git commit -m "feat(daemon): add goal breakdown model and ThinkEngine goal tools"
```

---

## Task 9: Self-Mutation Tools with HITL Guard

**Files:**
- Create: `src/everstaff/daemon/mutation_tools.py`
- Test: `tests/test_daemon/test_mutation_tools.py`

**Step 1: Write failing tests**

```python
# tests/test_daemon/test_mutation_tools.py
"""Tests for self-mutation tools with HITL guard."""
import pytest
import yaml
from pathlib import Path

from everstaff.daemon.mutation_tools import (
    validate_no_permission_mutation,
    PermissionMutationForbidden,
    build_mutation_hitl_request,
)


def test_reject_permission_mutation():
    """Any change touching permissions is forbidden."""
    with pytest.raises(PermissionMutationForbidden):
        validate_no_permission_mutation({"permissions": {"allow": ["Bash"]}})


def test_reject_allow_field():
    with pytest.raises(PermissionMutationForbidden):
        validate_no_permission_mutation({"allow": ["Read"]})


def test_reject_deny_field():
    with pytest.raises(PermissionMutationForbidden):
        validate_no_permission_mutation({"deny": ["Bash(rm *)"]})


def test_accept_non_permission_change():
    """Non-permission fields pass validation."""
    validate_no_permission_mutation({"skills": ["new-skill"]})
    validate_no_permission_mutation({"instructions": "new instructions"})
    validate_no_permission_mutation({"mcp_servers": [{"name": "gh"}]})


def test_build_hitl_request():
    req = build_mutation_hitl_request(
        agent_name="bot",
        mutation_type="update_agent_skills",
        current_value=["skill-a"],
        proposed_value=["skill-a", "skill-b"],
        reasoning="need skill-b for code review",
    )
    assert req.type == "approve_reject"
    assert "skill-b" in req.prompt
    assert "bot" in req.prompt


def test_apply_yaml_mutation_skills(tmp_path):
    """apply_yaml_mutation correctly updates skills field."""
    from everstaff.daemon.mutation_tools import apply_yaml_mutation

    spec_path = tmp_path / "bot.yaml"
    spec_path.write_text(yaml.dump({
        "agent_name": "bot",
        "skills": ["skill-a"],
        "permissions": {"allow": ["Bash"]},
    }))

    apply_yaml_mutation(spec_path, "skills", ["skill-a", "skill-b"])

    updated = yaml.safe_load(spec_path.read_text())
    assert "skill-b" in updated["skills"]
    # Permissions must be untouched
    assert updated["permissions"]["allow"] == ["Bash"]


def test_apply_yaml_mutation_refuses_permissions(tmp_path):
    from everstaff.daemon.mutation_tools import apply_yaml_mutation

    spec_path = tmp_path / "bot.yaml"
    spec_path.write_text(yaml.dump({"agent_name": "bot", "permissions": {"allow": []}}))

    with pytest.raises(PermissionMutationForbidden):
        apply_yaml_mutation(spec_path, "permissions", {"allow": ["*"]})
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/yuriiiz/Projects/everstaff && python -m pytest tests/test_daemon/test_mutation_tools.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Write implementation**

```python
# src/everstaff/daemon/mutation_tools.py
"""Self-mutation tools — allow agents to modify their own config with HITL guard.

HARD CONSTRAINT: Any mutation touching permissions/allow/deny is FORBIDDEN.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_FORBIDDEN_KEYS = frozenset({"permissions", "allow", "deny"})


class PermissionMutationForbidden(Exception):
    """Raised when a mutation attempts to change permission-related fields."""


def validate_no_permission_mutation(changes: dict[str, Any]) -> None:
    """Raise PermissionMutationForbidden if changes touch forbidden keys."""
    for key in changes:
        if key in _FORBIDDEN_KEYS:
            raise PermissionMutationForbidden(
                f"Mutation of '{key}' is forbidden. Permission fields cannot be self-modified."
            )


def build_mutation_hitl_request(
    *,
    agent_name: str,
    mutation_type: str,
    current_value: Any,
    proposed_value: Any,
    reasoning: str,
) -> Any:
    """Build a HitlRequestPayload describing the proposed self-mutation."""
    from everstaff.schema.hitl_models import HitlRequestPayload

    prompt = (
        f"Agent '{agent_name}' requests self-modification:\n\n"
        f"**Type:** {mutation_type}\n"
        f"**Reason:** {reasoning}\n\n"
        f"**Current value:**\n```\n{_format_value(current_value)}\n```\n\n"
        f"**Proposed value:**\n```\n{_format_value(proposed_value)}\n```\n\n"
        f"Approve this change?"
    )
    return HitlRequestPayload(
        type="approve_reject",
        prompt=prompt,
        context=f"Self-mutation: {mutation_type}",
    )


def apply_yaml_mutation(spec_path: Path, field: str, value: Any) -> None:
    """Apply a mutation to an agent YAML file.

    Raises PermissionMutationForbidden if field is permissions-related.
    """
    if field in _FORBIDDEN_KEYS:
        raise PermissionMutationForbidden(
            f"Cannot mutate '{field}' — permission fields are immutable."
        )

    data = yaml.safe_load(spec_path.read_text())
    data[field] = value
    spec_path.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True))
    logger.info("[MutationTools] Applied mutation to %s: field=%s", spec_path.name, field)


def _format_value(v: Any) -> str:
    if isinstance(v, (list, dict)):
        return yaml.dump(v, default_flow_style=False).strip()
    return str(v)
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/yuriiiz/Projects/everstaff && python -m pytest tests/test_daemon/test_mutation_tools.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/everstaff/daemon/mutation_tools.py tests/test_daemon/test_mutation_tools.py
git commit -m "feat(daemon): add self-mutation tools with HITL guard and permission firewall"
```

---

## Task 10: Learning Cycle — ThinkEngine insight recording

**Files:**
- Modify: `src/everstaff/daemon/think_engine.py` (add `record_learning_insight` tool)
- Test: `tests/test_daemon/test_learning_cycle.py`

**Step 1: Write failing tests**

```python
# tests/test_daemon/test_learning_cycle.py
"""Tests for the learning cycle — insight recording via ThinkEngine."""
import pytest
from everstaff.protocols import ToolDefinition


def test_record_learning_insight_tool_exists():
    from everstaff.daemon.think_engine import THINK_TOOLS

    names = [t.name for t in THINK_TOOLS]
    assert "record_learning_insight" in names


def test_record_learning_insight_tool_schema():
    from everstaff.daemon.think_engine import THINK_TOOLS

    tool = next(t for t in THINK_TOOLS if t.name == "record_learning_insight")
    params = tool.parameters
    required = params.get("required", [])
    assert "category" in required
    assert "insight" in required
    assert "evidence" in required
    props = params["properties"]
    assert "category" in props
    assert "insight" in props
    assert "evidence" in props
    assert "action" in props
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/yuriiiz/Projects/everstaff && python -m pytest tests/test_daemon/test_learning_cycle.py -v`
Expected: FAIL — `record_learning_insight` not in THINK_TOOLS

**Step 3: Add tool to THINK_TOOLS and handle in think loop**

In `src/everstaff/daemon/think_engine.py`, add to `THINK_TOOLS`:

```python
ToolDefinition(
    name="record_learning_insight",
    description="Record a learning insight from analyzing recent episodes. Insights are persisted and inform future decisions.",
    parameters={
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "enum": ["pattern", "optimization", "risk", "capability_gap"],
                "description": "Type of insight",
            },
            "insight": {"type": "string", "description": "What was learned"},
            "evidence": {"type": "string", "description": "Episode IDs or summary supporting this insight"},
            "action": {"type": "string", "description": "Recommended follow-up action (may trigger self-mutation)"},
        },
        "required": ["category", "insight", "evidence"],
    },
),
```

In the think loop, handle `record_learning_insight` tool calls by writing to semantic memory under topic `learning_insights`:

```python
elif tool_call.name == "record_learning_insight":
    args = json.loads(tool_call.arguments) if isinstance(tool_call.arguments, str) else tool_call.arguments
    # Append insight to semantic memory
    existing = await self._memory.semantic_read(agent_name, "learning_insights")
    entry = f"\n[{args['category']}] {args['insight']} (evidence: {args['evidence']})"
    if args.get("action"):
        entry += f" → action: {args['action']}"
    updated = (existing + entry) if existing else entry
    await self._memory.semantic_write(agent_name, "learning_insights", updated)
    messages.append(Message(role="tool", content="Insight recorded.", tool_call_id=tool_call.id))
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/yuriiiz/Projects/everstaff && python -m pytest tests/test_daemon/test_learning_cycle.py -v`
Expected: ALL PASS

**Step 5: Update ThinkEngine system prompt to include insights**

In `_build_system_prompt` (line ~347), add a section that loads `learning_insights` from semantic memory topics if present, so future think cycles see past insights.

**Step 6: Run full daemon test suite**

Run: `cd /Users/yuriiiz/Projects/everstaff && python -m pytest tests/test_daemon/ -v`
Expected: ALL PASS

**Step 7: Commit**

```bash
git add src/everstaff/daemon/think_engine.py tests/test_daemon/test_learning_cycle.py
git commit -m "feat(daemon): add learning cycle with record_learning_insight tool in ThinkEngine"
```

---

## Task 11: Wire self-mutation tools into runtime (act phase)

**Files:**
- Create: `src/everstaff/daemon/mutation_tool_provider.py`
- Modify: `src/everstaff/daemon/agent_daemon.py` (pass mutation tools to runtime factory)
- Test: `tests/test_daemon/test_mutation_tool_provider.py`

**Step 1: Write failing tests**

```python
# tests/test_daemon/test_mutation_tool_provider.py
"""Tests for mutation tool provider."""
import pytest
from everstaff.daemon.mutation_tool_provider import MutationToolProvider


def test_provider_returns_tool_definitions():
    provider = MutationToolProvider(
        agent_name="bot",
        agent_yaml_path="/tmp/bot.yaml",
        daemon_reload_fn=lambda: None,
    )
    tools = provider.get_tools()
    names = [t.name for t in tools]
    assert "update_agent_skills" in names
    assert "update_agent_mcp" in names
    assert "update_agent_instructions" in names
    assert "update_agent_triggers" in names


def test_provider_does_not_expose_permission_tools():
    provider = MutationToolProvider(
        agent_name="bot",
        agent_yaml_path="/tmp/bot.yaml",
        daemon_reload_fn=lambda: None,
    )
    tools = provider.get_tools()
    names = [t.name for t in tools]
    # No tool should allow permission modification
    assert "update_agent_permissions" not in names
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/yuriiiz/Projects/everstaff && python -m pytest tests/test_daemon/test_mutation_tool_provider.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Write implementation**

```python
# src/everstaff/daemon/mutation_tool_provider.py
"""MutationToolProvider — provides self-mutation tools for daemon agents.

These tools are injected into the agent's runtime during act phase.
Each tool triggers HITL approval before applying changes.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from everstaff.protocols import ToolDefinition

logger = logging.getLogger(__name__)

_MUTATION_FIELDS = {
    "update_agent_skills": ("skills", "Add, remove, or modify the agent's skills list"),
    "update_agent_mcp": ("mcp_servers", "Add or remove MCP server configurations"),
    "update_agent_instructions": ("instructions", "Modify the agent's system instructions"),
    "update_agent_triggers": ("autonomy.triggers", "Add or modify autonomy triggers"),
}


class MutationToolProvider:
    """Provides self-mutation ToolDefinitions for a specific agent."""

    def __init__(
        self,
        agent_name: str,
        agent_yaml_path: str | Path,
        daemon_reload_fn: Callable,
    ) -> None:
        self._agent_name = agent_name
        self._yaml_path = Path(agent_yaml_path)
        self._reload_fn = daemon_reload_fn

    def get_tools(self) -> list[ToolDefinition]:
        tools = []
        for tool_name, (field, description) in _MUTATION_FIELDS.items():
            tools.append(ToolDefinition(
                name=tool_name,
                description=f"{description}. Requires HITL approval. Cannot modify permissions.",
                parameters={
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["add", "remove", "replace"],
                            "description": "Type of mutation",
                        },
                        "value": {
                            "description": f"The new value for {field}",
                        },
                        "reasoning": {
                            "type": "string",
                            "description": "Why this change is needed",
                        },
                    },
                    "required": ["action", "value", "reasoning"],
                },
            ))
        return tools
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/yuriiiz/Projects/everstaff && python -m pytest tests/test_daemon/test_mutation_tool_provider.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/everstaff/daemon/mutation_tool_provider.py tests/test_daemon/test_mutation_tool_provider.py
git commit -m "feat(daemon): add MutationToolProvider for self-mutation tools in act phase"
```

---

## Task 12: Integration test — full learning cycle

**Files:**
- Test: `tests/test_daemon/test_learning_integration.py`

**Step 1: Write integration test**

```python
# tests/test_daemon/test_learning_integration.py
"""Integration test: InternalSensor triggers learning cycle in ThinkEngine."""
import asyncio
import pytest

from everstaff.daemon.event_bus import EventBus
from everstaff.daemon.sensors.internal import InternalSensor
from everstaff.schema.autonomy import TriggerConfig


@pytest.mark.asyncio
async def test_episode_accumulation_triggers_reflection_event():
    """After N episodes, InternalSensor fires a reflection event."""
    bus = EventBus()
    bus.subscribe("learner")

    trigger = TriggerConfig(
        id="reflect", type="internal", condition="episode_count",
        threshold=3, task="analyze recent episodes",
    )
    sensor = InternalSensor(triggers=[trigger], agent_name="learner")
    await sensor.start(bus)

    # Simulate 3 episodes
    for _ in range(3):
        sensor.notify_episode()

    event = await asyncio.wait_for(bus.wait_for("learner", timeout=1), timeout=2)
    assert event is not None
    assert event.source == "internal"
    assert event.type == "internal.reflect"
    assert event.payload["task"] == "analyze recent episodes"
    assert event.payload["condition"] == "episode_count"

    # Counter should have reset
    sensor.notify_episode()
    no_event = await bus.wait_for("learner", timeout=0.1)
    assert no_event is None

    await sensor.stop()


@pytest.mark.asyncio
async def test_mutation_tools_block_permission_changes():
    """Self-mutation tools hard-reject permission mutations."""
    from everstaff.daemon.mutation_tools import validate_no_permission_mutation, PermissionMutationForbidden

    # Must reject all permission-related keys
    for key in ("permissions", "allow", "deny"):
        with pytest.raises(PermissionMutationForbidden):
            validate_no_permission_mutation({key: "anything"})

    # Must accept non-permission keys
    for key in ("skills", "instructions", "mcp_servers", "autonomy"):
        validate_no_permission_mutation({key: "anything"})  # no error
```

**Step 2: Run integration test**

Run: `cd /Users/yuriiiz/Projects/everstaff && python -m pytest tests/test_daemon/test_learning_integration.py -v`
Expected: ALL PASS

**Step 3: Run full test suite**

Run: `cd /Users/yuriiiz/Projects/everstaff && python -m pytest tests/test_daemon/ -v`
Expected: ALL PASS

**Step 4: Commit**

```bash
git add tests/test_daemon/test_learning_integration.py
git commit -m "test(daemon): add integration tests for learning cycle and permission firewall"
```

---

## Task 13: Update daemon API for webhook endpoint visibility

**Files:**
- Modify: `src/everstaff/api/daemon.py`
- Test: existing daemon API tests (verify no regression)

**Step 1: Add webhook info to /api/daemon/status**

In `src/everstaff/api/daemon.py`, extend the `/status` endpoint response:

```python
@daemon_router.get("/status")
async def daemon_status(request: Request):
    daemon = getattr(request.app.state, "daemon", None)
    if daemon is None:
        return {"enabled": False, "running": False, "webhooks": []}
    webhooks = []
    for sensor, agent_name in daemon.sensor_manager._sensors:
        if hasattr(sensor, "_route_path") and sensor._route_path:
            webhooks.append({
                "agent_name": agent_name,
                "path": sensor._route_path,
            })
    return {
        "enabled": True,
        "running": daemon.is_running,
        "webhooks": webhooks,
    }
```

**Step 2: Run daemon API tests**

Run: `cd /Users/yuriiiz/Projects/everstaff && python -m pytest tests/ -k daemon -v`
Expected: ALL PASS

**Step 3: Commit**

```bash
git add src/everstaff/api/daemon.py
git commit -m "feat(api): expose webhook endpoint paths in daemon status"
```

---

## Summary of deliverables

| Task | Component | New Files | Modified Files |
|---|---|---|---|
| 1 | Sensor ABC | `sensors/base.py`, test | — |
| 2 | SchedulerSensor refactor | — | `sensors/scheduler.py`, test |
| 3 | TriggerConfig schema | test | `schema/autonomy.py` |
| 4 | WebhookSensor | `sensors/webhook.py`, test | — |
| 5 | FileWatchSensor | `sensors/file_watch.py`, test | — |
| 6 | InternalSensor | `sensors/internal.py`, test | — |
| 7 | Wire sensors into daemon | test | `agent_daemon.py`, `agent_loop.py` |
| 8 | Goal breakdown | `goals.py`, test | `think_engine.py` |
| 9 | Self-mutation tools | `mutation_tools.py`, test | — |
| 10 | Learning cycle | test | `think_engine.py` |
| 11 | Mutation tool provider | `mutation_tool_provider.py`, test | — |
| 12 | Integration tests | test | — |
| 13 | API webhook visibility | — | `api/daemon.py` |

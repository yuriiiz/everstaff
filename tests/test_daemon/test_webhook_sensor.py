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

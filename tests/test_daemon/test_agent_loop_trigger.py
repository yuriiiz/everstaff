import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_agent_loop_passes_trigger_to_factory():
    """AgentLoop.run_once() passes the triggering AgentEvent to the runtime factory."""
    from everstaff.daemon.agent_loop import AgentLoop
    from everstaff.daemon.event_bus import EventBus
    from everstaff.protocols import AgentEvent, Decision

    received_kwargs = {}

    def mock_factory(**kw):
        received_kwargs.update(kw)
        mock_runtime = MagicMock()
        mock_runtime.run = AsyncMock(return_value="ok")
        return mock_runtime

    mock_think = MagicMock()
    mock_think.think = AsyncMock(return_value=Decision(
        action="execute", reasoning="test", task_prompt="do something"
    ))

    bus = EventBus()

    mock_memory = MagicMock()
    mock_memory.working_load = AsyncMock(return_value=MagicMock(recent_decisions=[]))
    mock_memory.working_save = AsyncMock()
    mock_memory.episode_append = AsyncMock()

    loop = AgentLoop(
        agent_name="test-agent",
        event_bus=bus,
        think_engine=mock_think,
        runtime_factory=mock_factory,
        memory=mock_memory,
        tracer=MagicMock(on_event=MagicMock()),
    )

    # Subscribe the agent to the bus so it has a queue, then publish the event
    bus.subscribe("test-agent")
    event = AgentEvent(source="scheduler", type="cron", id="evt-42", target_agent="test-agent")
    await bus.publish(event)
    await loop.run_once()

    assert "trigger" in received_kwargs, f"trigger not in factory kwargs: {received_kwargs.keys()}"
    assert received_kwargs["trigger"].source == "scheduler"
    assert received_kwargs["trigger"].id == "evt-42"

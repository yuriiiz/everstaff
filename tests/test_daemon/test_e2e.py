"""End-to-end integration test for the full daemon pipeline.

Validates the complete cycle: YAML parsing -> sensor firing -> EventBus ->
ThinkEngine -> AgentLoop -> Runtime -> Memory.

Uses real EventBus, SchedulerSensor (with apscheduler), LoopManager,
SensorManager, and ThinkEngine, but mocks LLM and runtime.
"""
import asyncio
import pytest
from pathlib import Path

from everstaff.daemon.agent_daemon import AgentDaemon
from everstaff.nulls import InMemoryStore, NullTracer
from everstaff.protocols import LLMResponse, ToolCallRequest, Decision


class MockLLM:
    """Mock LLM that returns a make_decision tool call."""
    async def complete(self, messages, tools, system=None):
        return LLMResponse(
            content=None,
            tool_calls=[ToolCallRequest(
                id="tc-1",
                name="make_decision",
                args={
                    "action": "execute",
                    "task_prompt": "check system status",
                    "reasoning": "scheduled periodic check",
                    "priority": "normal",
                },
            )],
        )


class MockRuntime:
    """Mock runtime that returns a fixed result."""
    def __init__(self):
        self.called = False
        self.last_prompt = ""

    async def run(self, prompt: str, session_id: str = "", parent_session_id: str = ""):
        self.called = True
        self.last_prompt = prompt
        return "System healthy. All services running."


def _write_autonomous_agent_yaml(agents_dir: Path, name: str = "monitor"):
    """Write a test agent YAML with a fast interval trigger."""
    yaml_content = f"""
uuid: "{name}-uuid-001"
name: {name}
description: "System monitoring agent"
instructions: "You monitor system health."
autonomy:
  enabled: true
  level: supervised
  tick_interval: 1
  triggers:
    - id: fast_check
      type: interval
      every: 1
      task: "check system status"
"""
    (agents_dir / f"{name}.yaml").write_text(yaml_content)


@pytest.mark.asyncio
async def test_daemon_full_cycle(tmp_path):
    """
    End-to-end test:
    1. Create agent YAML with autonomy.enabled + interval trigger (1s)
    2. Start AgentDaemon
    3. Wait for one cycle to complete
    4. Verify: episode written to L2, working memory updated
    5. Stop daemon
    """
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    _write_autonomous_agent_yaml(agents_dir, "monitor")

    memory = InMemoryStore()
    tracer = NullTracer()
    mock_runtime = MockRuntime()

    daemon = AgentDaemon(
        agents_dir=agents_dir,
        memory=memory,
        tracer=tracer,
        llm_factory=lambda **kw: MockLLM(),
        runtime_factory=lambda **kw: mock_runtime,
    )

    await daemon.start()
    assert daemon.is_running
    assert daemon.loop_manager.has("monitor")

    # Wait for at least one cycle to complete (sensor fires every 1s, plus processing time)
    for _ in range(30):
        await asyncio.sleep(0.5)
        episodes = await memory.episode_query("monitor")
        if len(episodes) > 0:
            break

    # Verify memory was updated
    episodes = await memory.episode_query("monitor")
    assert len(episodes) >= 1, f"Expected at least 1 episode, got {len(episodes)}"
    assert episodes[0].action == "check system status"
    assert "healthy" in episodes[0].result.lower() or "running" in episodes[0].result.lower()

    # Verify working memory has recent decisions
    ws = await memory.working_load("monitor")
    assert len(ws.recent_decisions) >= 1
    assert ws.recent_decisions[-1]["action"] == "execute"

    # Verify runtime was called
    assert mock_runtime.called
    assert mock_runtime.last_prompt == "check system status"

    await daemon.stop()
    assert not daemon.is_running

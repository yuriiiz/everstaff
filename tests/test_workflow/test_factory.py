import pytest
from unittest.mock import AsyncMock, patch


def make_sub_agent_spec(name: str):
    from everstaff.schema.agent_spec import SubAgentSpec
    return SubAgentSpec(name=name, description=f"{name} agent", instructions="do stuff")


@pytest.mark.asyncio
async def test_factory_run_unknown_agent_returns_error():
    from everstaff.workflow.factory import WorkflowSubAgentFactory
    from everstaff.builder.environment import TestEnvironment
    from everstaff.protocols import CancellationEvent

    factory = WorkflowSubAgentFactory(
        available_agents={},
        env=TestEnvironment(),
        parent_session_id="parent-1",
        parent_cancellation=CancellationEvent(),
        parent_model_id="claude-3-5-haiku",
    )
    result = await factory.run("nonexistent", "do something")
    assert "[Error]" in result
    assert "nonexistent" in result


@pytest.mark.asyncio
async def test_factory_run_spawns_agent_builder(tmp_path):
    from everstaff.workflow.factory import WorkflowSubAgentFactory
    from everstaff.builder.environment import TestEnvironment
    from everstaff.protocols import CancellationEvent

    spec = make_sub_agent_spec("coder")
    factory = WorkflowSubAgentFactory(
        available_agents={"coder": spec},
        env=TestEnvironment(),
        parent_session_id="parent-1",
        parent_cancellation=CancellationEvent(),
        parent_model_id="claude-3-5-haiku",
    )

    with patch("everstaff.workflow.factory.AgentBuilder") as MockBuilder:
        mock_runtime = AsyncMock()
        mock_runtime.run = AsyncMock(return_value="done")
        mock_ctx = AsyncMock()
        mock_ctx.cancellation = CancellationEvent()
        MockBuilder.return_value.build = AsyncMock(return_value=(mock_runtime, mock_ctx))

        result = await factory.run("coder", "write some code")

    assert result == "done"
    MockBuilder.assert_called_once()
    call_kwargs = MockBuilder.call_args
    assert call_kwargs.kwargs["parent_session_id"] == "parent-1"


@pytest.mark.asyncio
async def test_factory_passes_parent_cancellation():
    from everstaff.workflow.factory import WorkflowSubAgentFactory
    from everstaff.builder.environment import TestEnvironment
    from everstaff.protocols import CancellationEvent

    parent_cancel = CancellationEvent()
    spec = make_sub_agent_spec("writer")
    factory = WorkflowSubAgentFactory(
        available_agents={"writer": spec},
        env=TestEnvironment(),
        parent_session_id="p1",
        parent_cancellation=parent_cancel,
        parent_model_id="claude-3-5-haiku",
    )

    with patch("everstaff.workflow.factory.AgentBuilder") as MockBuilder:
        mock_runtime = AsyncMock()
        mock_runtime.run = AsyncMock(return_value="ok")
        mock_ctx = AsyncMock()
        mock_ctx.cancellation = parent_cancel
        MockBuilder.return_value.build = AsyncMock(return_value=(mock_runtime, mock_ctx))

        await factory.run("writer", "write something")

    # parent_cancellation is passed through
    call_kwargs = MockBuilder.call_args
    assert call_kwargs.kwargs["parent_cancellation"] is parent_cancel


@pytest.mark.asyncio
async def test_factory_run_calls_ctx_aclose_on_success():
    """WorkflowSubAgentFactory.run() must call ctx.aclose() after runtime.run()."""
    from unittest.mock import AsyncMock, patch, MagicMock
    from everstaff.workflow.factory import WorkflowSubAgentFactory

    mock_ctx = AsyncMock()
    mock_runtime = AsyncMock()
    mock_runtime.run = AsyncMock(return_value="result")

    sub_spec = MagicMock()
    sub_spec.to_agent_spec.return_value = MagicMock()

    factory = WorkflowSubAgentFactory(
        available_agents={"worker": sub_spec},
        env=MagicMock(),
        parent_session_id="parent-sess",
        parent_cancellation=MagicMock(),
        parent_model_id="gpt-4",
    )

    with patch("everstaff.workflow.factory.AgentBuilder") as MockBuilder:
        MockBuilder.return_value.build = AsyncMock(return_value=(mock_runtime, mock_ctx))
        result = await factory.run("worker", "do the thing")

    assert result == "result"
    mock_ctx.aclose.assert_called_once()


@pytest.mark.asyncio
async def test_factory_run_calls_ctx_aclose_on_failure():
    """WorkflowSubAgentFactory.run() must call ctx.aclose() even when runtime.run() raises."""
    from unittest.mock import AsyncMock, patch, MagicMock
    from everstaff.workflow.factory import WorkflowSubAgentFactory

    mock_ctx = AsyncMock()
    mock_runtime = AsyncMock()
    mock_runtime.run = AsyncMock(side_effect=RuntimeError("agent crashed"))

    sub_spec = MagicMock()
    sub_spec.to_agent_spec.return_value = MagicMock()

    factory = WorkflowSubAgentFactory(
        available_agents={"worker": sub_spec},
        env=MagicMock(),
        parent_session_id="parent-sess",
        parent_cancellation=MagicMock(),
        parent_model_id="gpt-4",
    )

    with patch("everstaff.workflow.factory.AgentBuilder") as MockBuilder:
        MockBuilder.return_value.build = AsyncMock(return_value=(mock_runtime, mock_ctx))
        with pytest.raises(RuntimeError, match="agent crashed"):
            await factory.run("worker", "do the thing")

    mock_ctx.aclose.assert_called_once()

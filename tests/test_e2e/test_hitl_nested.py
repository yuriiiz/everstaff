"""E2E test: nested HITL bubbling — child HITL stored in session.json and resumable."""
import json
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_child_hitl_stored_in_session_json_on_raise(tmp_path):
    """Full flow: child raises HumanApprovalRequired → runtime saves hitl_requests in session.json."""
    from everstaff.core.runtime import AgentRuntime
    from everstaff.protocols import (
        HumanApprovalRequired, HitlRequest, LLMResponse,
        ToolCallRequest, Message,
    )

    saved_payload = {}

    class CapturingMemory:
        async def load(self, sid):
            return []

        async def save(self, sid, msgs, **kw):
            saved_payload.update(kw)
            saved_payload["_messages"] = msgs
            saved_payload["_session_id"] = sid

    hitl_req = HitlRequest(
        hitl_id="e2e-hitl-1",
        type="choose",
        prompt="Pick a region",
        options=["us-east", "eu-west"],
    )

    llm = MagicMock()
    llm.complete_stream = None  # prevent MagicMock auto-attribute from triggering streaming path
    llm.complete = AsyncMock(return_value=LLMResponse(
        content=None,
        tool_calls=[ToolCallRequest(id="tc-1", name="request_human_input",
                                    args={"type": "choose", "prompt": "Pick a region"})],
    ))

    from everstaff.core.context import AgentContext
    from everstaff.tools.pipeline import ToolCallPipeline
    from everstaff.tools.stages import ExecutionStage
    from everstaff.tools.default_registry import DefaultToolRegistry
    from everstaff.nulls import NullTracer

    reg = DefaultToolRegistry()
    pipeline = ToolCallPipeline([ExecutionStage(reg)])
    ctx = AgentContext(
        tool_registry=reg,
        memory=CapturingMemory(),
        tool_pipeline=pipeline,
        tracer=NullTracer(),
        agent_name="e2e-agent",
        session_id="e2e-session-001",
    )

    runtime = AgentRuntime(context=ctx, llm_client=llm)
    with pytest.raises(HumanApprovalRequired) as exc_info:
        with patch.object(ctx.tool_pipeline, "execute", side_effect=HumanApprovalRequired(hitl_req)):
            async for _ in runtime.run_stream("pick for me"):
                pass

    # Verify the exception carries the request
    assert len(exc_info.value.requests) == 1
    assert exc_info.value.requests[0].hitl_id == "e2e-hitl-1"

    # Verify session.json was saved with hitl_requests embedded
    assert saved_payload.get("status") == "waiting_for_human"
    hitl_data = saved_payload.get("hitl_requests", [])
    assert len(hitl_data) == 1
    h = hitl_data[0]
    assert h["hitl_id"] == "e2e-hitl-1"
    assert h["status"] == "pending"
    assert h["tool_call_id"] == "tc-1"
    assert h["request"]["type"] == "choose"
    assert h["request"]["prompt"] == "Pick a region"
    assert h["response"] is None


@pytest.mark.asyncio
async def test_hitl_resolve_triggers_resume_only_when_all_settled(tmp_path):
    """POST /hitl/{id}/resolve triggers resume only when ALL HITLs in session are resolved."""
    from fastapi.testclient import TestClient
    from everstaff.api import create_app

    sessions_dir = tmp_path / "sessions"
    sid = "sess-multi"
    (sessions_dir / sid).mkdir(parents=True)
    now = datetime.now(timezone.utc).isoformat()

    session_data = {
        "session_id": sid,
        "agent_name": "test-agent",
        "created_at": now,
        "updated_at": now,
        "status": "waiting_for_human",
        "metadata": {},
        "messages": [],
        "hitl_requests": [
            {
                "hitl_id": "h-e2e-1",
                "tool_call_id": "tc-e2e-1",
                "created_at": now,
                "timeout_seconds": 86400,
                "status": "pending",
                "origin_session_id": sid,
                "origin_agent_name": "test-agent",
                "request": {"type": "approve_reject", "prompt": "Allow A?", "options": [], "context": ""},
                "response": None,
            },
            {
                "hitl_id": "h-e2e-2",
                "tool_call_id": "tc-e2e-2",
                "created_at": now,
                "timeout_seconds": 86400,
                "status": "pending",
                "origin_session_id": sid,
                "origin_agent_name": "test-agent",
                "request": {"type": "approve_reject", "prompt": "Allow B?", "options": [], "context": ""},
                "response": None,
            },
        ],
    }
    (sessions_dir / sid / "session.json").write_text(json.dumps(session_data))

    resumed = []

    async def fake_resume(*args, **kwargs):
        resumed.append(args[0])  # session_id

    app = create_app(sessions_dir=str(sessions_dir))
    with patch("everstaff.api.sessions._resume_session_task", fake_resume):
        client = TestClient(app)
        # Resolve first — should NOT trigger resume
        r1 = client.post("/api/hitl/h-e2e-1/resolve", json={"decision": "approved"})
        assert r1.status_code == 200
        assert resumed == []  # still waiting for h-e2e-2

        # Resolve second — should trigger resume
        r2 = client.post("/api/hitl/h-e2e-2/resolve", json={"decision": "rejected"})
        assert r2.status_code == 200
        assert sid in resumed  # both settled → resume triggered


@pytest.mark.asyncio
async def test_delegate_tool_child_hitl_bubbles_as_structured_result():
    """DelegateTaskTool returns [SUB_AGENT_HITL] tool result when child raises HumanApprovalRequired."""
    from everstaff.agents.delegate_task_tool import DelegateTaskTool
    from everstaff.protocols import HumanApprovalRequired, HitlRequest
    from everstaff.schema.agent_spec import SubAgentSpec
    from everstaff.builder.environment import TestEnvironment

    def make_spec(name):
        spec = MagicMock(spec=SubAgentSpec)
        spec.name = name
        spec.description = f"{name} agent"
        spec.to_agent_spec = MagicMock(return_value=MagicMock())
        return spec

    tool = DelegateTaskTool(specs=[make_spec("child")], env=TestEnvironment())
    child_requests = [
        HitlRequest(hitl_id="ch-1", type="approve_reject", prompt="Deploy?"),
        HitlRequest(hitl_id="ch-2", type="choose", prompt="Region?", options=["us", "eu"]),
    ]

    mock_runtime = MagicMock()
    mock_runtime.run = AsyncMock(side_effect=HumanApprovalRequired(child_requests))
    mock_runtime.stats = None
    mock_ctx = MagicMock()
    mock_ctx.session_id = "child-sess-e2e"
    mock_ctx.memory = AsyncMock()
    mock_ctx.aclose = AsyncMock()

    with patch("everstaff.agents.delegate_task_tool.AgentBuilder") as MockBuilder:
        mock_builder_instance = MagicMock()
        mock_builder_instance.build = AsyncMock(return_value=(mock_runtime, mock_ctx))
        MockBuilder.return_value = mock_builder_instance

        result = await tool.execute({"agent_name": "child", "prompt": "do it"})

    assert not result.is_error
    assert "[SUB_AGENT_HITL]" in result.content
    # Both requests listed
    assert "ch-1" in result.content
    assert "ch-2" in result.content
    assert "Deploy?" in result.content
    assert "Region?" in result.content

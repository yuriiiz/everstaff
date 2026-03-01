# tests/test_protocols.py


def test_protocols_importable():
    """All protocol types must be importable from everstaff.protocols"""
    from everstaff.protocols import (
        Tool, ToolDefinition, ToolResult,
        Message, TraceEvent, PermissionResult,
        ToolRegistry, MemoryStore, TracingBackend,
        PermissionChecker, SkillProvider, KnowledgeProvider,
        SubAgentProvider, LLMClient, LLMResponse,
        PromptInjector, McpProvider, CancellationEvent,
    )


def test_tool_definition_is_dataclass():
    from everstaff.protocols import ToolDefinition
    td = ToolDefinition(
        name="my_tool",
        description="does something",
        parameters={"type": "object", "properties": {}},
    )
    assert td.name == "my_tool"


def test_tool_result_as_message():
    from everstaff.protocols import ToolResult
    result = ToolResult(tool_call_id="call_1", content="hello")
    msg = result.as_message()
    assert msg["role"] == "tool"
    assert msg["content"] == "hello"
    assert msg["tool_call_id"] == "call_1"


def test_permission_result_allowed():
    from everstaff.protocols import PermissionResult
    ok = PermissionResult(allowed=True)
    assert ok.allowed
    assert ok.reason is None


def test_permission_result_denied():
    from everstaff.protocols import PermissionResult
    denied = PermissionResult(allowed=False, reason="blocked by deny rule")
    assert not denied.allowed
    assert "deny" in denied.reason


def test_prompt_injector_protocol_exists():
    from everstaff.protocols import PromptInjector
    assert hasattr(PromptInjector, "get_prompt_injection")

def test_skill_provider_is_prompt_injector():
    from everstaff.protocols import PromptInjector
    from everstaff.nulls import NullSkillProvider
    provider = NullSkillProvider()
    assert isinstance(provider, PromptInjector)

def test_knowledge_provider_is_prompt_injector():
    from everstaff.protocols import PromptInjector
    from everstaff.nulls import NullKnowledgeProvider
    assert isinstance(NullKnowledgeProvider(), PromptInjector)

def test_sub_agent_provider_is_prompt_injector():
    from everstaff.protocols import PromptInjector
    from everstaff.nulls import NullSubAgentProvider
    assert isinstance(NullSubAgentProvider(), PromptInjector)

def test_mcp_provider_null_returns_empty_injection():
    from everstaff.nulls import NullMcpProvider
    from everstaff.protocols import PromptInjector
    p = NullMcpProvider()
    assert isinstance(p, PromptInjector)
    assert p.get_prompt_injection() == ""
    assert p.get_tools() == []

def test_null_skill_provider_uses_new_method_name():
    from everstaff.nulls import NullSkillProvider
    p = NullSkillProvider()
    assert p.get_prompt_injection() == ""


def test_trace_event_has_timestamp_and_duration():
    from everstaff.protocols import TraceEvent
    import dataclasses
    fields = {f.name for f in dataclasses.fields(TraceEvent)}
    assert "timestamp" in fields
    assert "duration_ms" in fields
    assert "parent_session_id" in fields


def test_cancellation_event_starts_uncancelled():
    from everstaff.protocols import CancellationEvent
    ce = CancellationEvent()
    assert not ce.is_cancelled
    assert not ce.is_force


def test_cancellation_event_cancel_graceful():
    from everstaff.protocols import CancellationEvent
    ce = CancellationEvent()
    ce.cancel(force=False)
    assert ce.is_cancelled
    assert not ce.is_force


def test_cancellation_event_cancel_force():
    from everstaff.protocols import CancellationEvent
    ce = CancellationEvent()
    ce.cancel(force=True)
    assert ce.is_cancelled
    assert ce.is_force


def test_cancellation_event_force_not_downgraded():
    from everstaff.protocols import CancellationEvent
    ce = CancellationEvent()
    ce.cancel(force=True)
    ce.cancel(force=False)   # should NOT downgrade force
    assert ce.is_force       # still True


# --- AgentEvent ---

def test_agent_event_defaults():
    from everstaff.protocols import AgentEvent
    e = AgentEvent()
    assert e.id  # uuid generated
    assert e.source == ""
    assert e.type == ""
    assert e.payload == {}
    assert e.target_agent is None
    assert e.timestamp  # auto-generated


def test_agent_event_with_values():
    from everstaff.protocols import AgentEvent
    e = AgentEvent(source="cron", type="cron.daily", payload={"task": "hi"}, target_agent="yuri")
    assert e.source == "cron"
    assert e.target_agent == "yuri"


# --- Episode ---

def test_episode_defaults():
    from everstaff.protocols import Episode
    ep = Episode(timestamp="2026-02-28T09:00:00Z", trigger="cron:daily", action="check email", result="3 emails")
    assert ep.duration_ms == 0
    assert ep.session_id == ""
    assert ep.tags == []


# --- WorkingState ---

def test_working_state_defaults():
    from everstaff.protocols import WorkingState
    ws = WorkingState()
    assert ws.goals_progress == {}
    assert ws.pending_items == []
    assert ws.recent_decisions == []
    assert ws.custom == {}


# --- Decision ---

def test_decision_execute():
    from everstaff.protocols import Decision
    d = Decision(action="execute", task_prompt="check email", reasoning="daily routine", priority="normal")
    assert d.action == "execute"


def test_decision_skip():
    from everstaff.protocols import Decision
    d = Decision(action="skip", reasoning="nothing to do")
    assert d.task_prompt == ""
    assert d.priority == "normal"


import pytest

@pytest.mark.asyncio
async def test_mcp_provider_protocol_has_aclose():
    """McpProvider protocol must declare aclose()."""
    import inspect
    from everstaff.protocols import McpProvider
    # Check aclose is declared as an abstract async method on the protocol
    assert hasattr(McpProvider, "aclose")
    assert inspect.iscoroutinefunction(McpProvider.aclose)

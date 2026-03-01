# tests/schema/test_session_models.py
import pytest
from everstaff.schema.memory import Session
from everstaff.schema.api_models import SessionMetadata
from everstaff.protocols import Message


def test_session_has_typed_messages():
    """Session.messages must be list[Message], not list[Any]."""
    msg = Message(role="user", content="hello")
    session = Session(
        session_id="s1",
        created_at="2025-01-01T00:00:00Z",
        updated_at="2025-01-01T00:00:00Z",
        messages=[msg],
    )
    assert len(session.messages) == 1
    assert isinstance(session.messages[0], Message)
    assert session.messages[0].role == "user"


def test_session_summary_removed():
    """SessionSummary must not exist in api_models."""
    import everstaff.schema.api_models as m
    assert not hasattr(m, "SessionSummary"), "SessionSummary should be removed"


def test_session_metadata_fields():
    """SessionMetadata must have all required fields with correct types."""
    from everstaff.schema.token_stats import TokenUsage
    meta = SessionMetadata(
        title="Test",
        own_calls=[TokenUsage(model_id="gpt-4o", input_tokens=5, output_tokens=10, total_tokens=15)],
        children_calls=[],
        tool_calls_count=2,
        errors_count=0,
        system_prompt="You are helpful.",
    )
    assert meta.title == "Test"
    assert meta.tool_calls_count == 2
    assert meta.own_calls[0].model_id == "gpt-4o"


def test_session_default_metadata():
    """Session with no explicit metadata should have a valid default."""
    from everstaff.schema.memory import Session
    from everstaff.schema.api_models import SessionMetadata
    s = Session(
        session_id="s2",
        created_at="2025-01-01T00:00:00Z",
        updated_at="2025-01-01T00:00:00Z",
    )
    assert isinstance(s.metadata, SessionMetadata)
    assert s.metadata.tool_calls_count == 0
    assert s.metadata.own_calls == []


def test_session_context_alias_removed():
    """SessionContext alias must not exist — all callers use SessionMetadata."""
    import everstaff.schema as schema
    assert not hasattr(schema, "SessionContext"), (
        "SessionContext backwards-compat alias was supposed to be removed. "
        "Check that no code still imports it."
    )

# tests/schema/test_token_usage.py
from everstaff.schema.token_stats import TokenUsage as StatsTokenUsage
from everstaff.schema.memory import TokenUsage as MemoryTokenUsage


def test_token_usage_is_same_class():
    """There must be only one TokenUsage class, imported from token_stats."""
    assert StatsTokenUsage is MemoryTokenUsage, (
        "TokenUsage in schema.memory must be the same object as schema.token_stats.TokenUsage"
    )


def test_token_usage_fields():
    u = StatsTokenUsage(model_id="gpt-4o", input_tokens=10, output_tokens=20, total_tokens=30)
    assert u.model_id == "gpt-4o"
    assert u.input_tokens == 10
    assert u.total_tokens == 30


def test_session_with_messages():
    from everstaff.schema.memory import Session
    from everstaff.protocols import Message
    msg = Message(role="user", content="hello")
    s = Session(
        session_id="s1",
        created_at="2025-01-01T00:00:00Z",
        updated_at="2025-01-01T00:00:00Z",
        messages=[msg],
    )
    assert s.session_id == "s1"
    assert len(s.messages) == 1
    assert s.messages[0].role == "user"

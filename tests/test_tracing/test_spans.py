import pytest
from dataclasses import asdict
from everstaff.protocols import TraceEvent


def test_trace_event_has_span_fields():
    """TraceEvent must have trace_id, span_id, parent_span_id."""
    event = TraceEvent(kind="session_start", session_id="sess-abc")
    assert hasattr(event, "trace_id")
    assert hasattr(event, "span_id")
    assert hasattr(event, "parent_span_id")


def test_trace_id_is_deterministic_from_session_id():
    """Same session_id always produces same trace_id."""
    e1 = TraceEvent(kind="session_start", session_id="sess-xyz")
    e2 = TraceEvent(kind="session_end", session_id="sess-xyz")
    assert e1.trace_id == e2.trace_id
    assert e1.trace_id != ""


def test_span_id_is_unique_per_event():
    """Each TraceEvent gets a different span_id."""
    e1 = TraceEvent(kind="llm_start", session_id="sess-xyz")
    e2 = TraceEvent(kind="llm_end", session_id="sess-xyz")
    assert e1.span_id != e2.span_id


def test_parent_span_id_defaults_to_none():
    event = TraceEvent(kind="session_start", session_id="sess-abc")
    assert event.parent_span_id is None


def test_trace_event_serializes_span_fields():
    """asdict() must include span fields for JSONL serialization."""
    event = TraceEvent(kind="test", session_id="sess-1")
    d = asdict(event)
    assert "trace_id" in d
    assert "span_id" in d
    assert "parent_span_id" in d

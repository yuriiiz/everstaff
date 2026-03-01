# tests/api/test_stream_events.py
from everstaff.schema.stream import TextDelta, ThinkingDelta, ToolCallStart, ToolCallEnd, TurnStart, SessionEnd, ErrorEvent


def test_text_delta_has_type_field():
    e = TextDelta(content="hello")
    assert e.type == "text_delta"
    assert e.content == "hello"


def test_tool_call_start_has_type():
    e = ToolCallStart(name="my_tool", args={"key": "val"})
    assert e.type == "tool_call_start"
    assert e.name == "my_tool"


def test_session_end_has_type():
    e = SessionEnd(response="done")
    assert e.type == "session_end"


def test_stream_event_discriminator():
    """StreamEvent union must resolve correctly via discriminator."""
    from pydantic import TypeAdapter
    from everstaff.schema.stream import StreamEvent
    ta = TypeAdapter(StreamEvent)
    event = ta.validate_python({"type": "text_delta", "content": "hi"})
    assert isinstance(event, TextDelta)
    assert event.content == "hi"

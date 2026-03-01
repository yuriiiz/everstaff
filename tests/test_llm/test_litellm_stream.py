import pytest
from unittest.mock import MagicMock, patch
from everstaff.llm.litellm_client import LiteLLMClient
from everstaff.protocols import Message, LLMResponse


def _make_chunk(content=None, tool_calls=None, usage=None):
    chunk = MagicMock()
    delta = MagicMock()
    delta.content = content
    delta.tool_calls = tool_calls or []
    delta.thinking = None
    delta.reasoning_content = None
    chunk.choices = [MagicMock(delta=delta)]
    chunk.usage = usage
    return chunk


@pytest.mark.asyncio
async def test_complete_stream_yields_text_and_done():
    chunks = [
        _make_chunk(content="Hello "),
        _make_chunk(content="world"),
        _make_chunk(content=None),
    ]

    async def fake_acompletion(**kwargs):
        for c in chunks:
            yield c

    client = LiteLLMClient(model="test-model")
    with patch("litellm.acompletion", return_value=fake_acompletion()):
        results = []
        async for kind, payload in client.complete_stream(
            messages=[Message(role="user", content="hi")],
            tools=[],
        ):
            results.append((kind, payload))

    text_events = [(k, p) for k, p in results if k == "text"]
    done_events = [(k, p) for k, p in results if k == "done"]

    assert len(done_events) == 1
    assert "".join(p for k, p in text_events) == "Hello world"
    resp = done_events[0][1]
    assert isinstance(resp, LLMResponse)
    assert resp.content == "Hello world"
    assert resp.tool_calls == []


@pytest.mark.asyncio
async def test_complete_stream_accumulates_tool_calls():
    tc0 = MagicMock()
    tc0.index = 0
    tc0.id = "call_abc"
    tc0.function = MagicMock()
    tc0.function.name = "read_file"
    tc0.function.arguments = '{"path"'

    tc1 = MagicMock()
    tc1.index = 0
    tc1.id = None
    tc1.function = MagicMock()
    tc1.function.name = None
    tc1.function.arguments = ': "foo.txt"}'

    chunks = [
        _make_chunk(tool_calls=[tc0]),
        _make_chunk(tool_calls=[tc1]),
        _make_chunk(),
    ]

    async def fake_acompletion(**kwargs):
        for c in chunks:
            yield c

    client = LiteLLMClient(model="test-model")
    with patch("litellm.acompletion", return_value=fake_acompletion()):
        results = []
        async for kind, payload in client.complete_stream(
            messages=[Message(role="user", content="hi")],
            tools=[],
        ):
            results.append((kind, payload))

    done = next(p for k, p in results if k == "done")
    assert len(done.tool_calls) == 1
    assert done.tool_calls[0].name == "read_file"
    assert done.tool_calls[0].args == {"path": "foo.txt"}


@pytest.mark.asyncio
async def test_complete_stream_no_text_chunks_when_only_tool_calls():
    """When LLM only returns tool calls (no text), no 'text' events should be yielded."""
    tc = MagicMock()
    tc.index = 0
    tc.id = "call_xyz"
    tc.function = MagicMock()
    tc.function.name = "bash"
    tc.function.arguments = '{"command": "ls"}'

    chunks = [_make_chunk(tool_calls=[tc]), _make_chunk()]

    async def fake_acompletion(**kwargs):
        for c in chunks:
            yield c

    client = LiteLLMClient(model="test-model")
    with patch("litellm.acompletion", return_value=fake_acompletion()):
        results = []
        async for kind, payload in client.complete_stream(
            messages=[Message(role="user", content="run ls")],
            tools=[],
        ):
            results.append((kind, payload))

    text_events = [k for k, _ in results if k == "text"]
    done_events = [p for k, p in results if k == "done"]
    assert len(text_events) == 0
    assert len(done_events) == 1
    assert done_events[0].content is None
    assert len(done_events[0].tool_calls) == 1

from unittest.mock import MagicMock, AsyncMock, patch
import pytest


@pytest.mark.asyncio
async def test_thinking_extracted_from_claude_response():
    """LiteLLMClient extracts thinking from Claude extended thinking response."""
    from everstaff.llm.litellm_client import LiteLLMClient
    from everstaff.protocols import Message

    mock_message = MagicMock()
    mock_message.content = "Final answer"
    mock_message.tool_calls = None
    mock_message.thinking = "Let me reason through this step by step..."  # Claude thinking

    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=mock_message)]
    mock_response.usage = MagicMock(prompt_tokens=10, completion_tokens=20)

    client = LiteLLMClient(model="claude-3-opus-20240229")
    with patch("litellm.acompletion", new=AsyncMock(return_value=mock_response)):
        result = await client.complete(
            messages=[Message(role="user", content="Think about it")],
            tools=[],
        )

    assert result.thinking == "Let me reason through this step by step..."
    assert result.content == "Final answer"


@pytest.mark.asyncio
async def test_reasoning_extracted_from_o1_response():
    """LiteLLMClient extracts reasoning_content from o1/o3 response."""
    from everstaff.llm.litellm_client import LiteLLMClient
    from everstaff.protocols import Message

    mock_message = MagicMock()
    mock_message.content = "42"
    mock_message.tool_calls = None
    mock_message.thinking = None
    mock_message.reasoning_content = "I need to calculate..."  # o1 reasoning

    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=mock_message)]
    mock_response.usage = MagicMock(prompt_tokens=5, completion_tokens=3)

    client = LiteLLMClient(model="o1-preview")
    with patch("litellm.acompletion", new=AsyncMock(return_value=mock_response)):
        result = await client.complete(
            messages=[Message(role="user", content="What is 6*7?")],
            tools=[],
        )

    assert result.thinking == "I need to calculate..."


@pytest.mark.asyncio
async def test_thinking_is_none_when_absent():
    """thinking is None when model returns no thinking."""
    from everstaff.llm.litellm_client import LiteLLMClient
    from everstaff.protocols import Message

    mock_message = MagicMock()
    mock_message.content = "Hello"
    mock_message.tool_calls = None
    mock_message.thinking = None
    mock_message.reasoning_content = None

    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=mock_message)]
    mock_response.usage = MagicMock(prompt_tokens=2, completion_tokens=1)

    client = LiteLLMClient(model="gpt-4")
    with patch("litellm.acompletion", new=AsyncMock(return_value=mock_response)):
        result = await client.complete(
            messages=[Message(role="user", content="Hi")],
            tools=[],
        )

    assert result.thinking is None

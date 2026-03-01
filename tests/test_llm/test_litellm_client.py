import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from everstaff.protocols import Message, ToolDefinition


@pytest.mark.asyncio
async def test_complete_returns_text_response():
    from everstaff.llm.litellm_client import LiteLLMClient

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "Hello!"
    mock_response.choices[0].message.tool_calls = None

    with patch("everstaff.llm.litellm_client.litellm.acompletion", new_callable=AsyncMock) as mock_complete:
        mock_complete.return_value = mock_response
        client = LiteLLMClient(model="gpt-4o-mini")
        result = await client.complete(
            messages=[Message(role="user", content="Hi")],
            tools=[],
        )
        assert result.content == "Hello!"
        assert result.is_final


@pytest.mark.asyncio
async def test_complete_returns_tool_calls():
    from everstaff.llm.litellm_client import LiteLLMClient

    mock_tool_call = MagicMock()
    mock_tool_call.id = "call_abc"
    mock_tool_call.function.name = "my_tool"
    mock_tool_call.function.arguments = '{"key": "value"}'

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = None
    mock_response.choices[0].message.tool_calls = [mock_tool_call]

    with patch("everstaff.llm.litellm_client.litellm.acompletion", new_callable=AsyncMock) as mock_complete:
        mock_complete.return_value = mock_response
        client = LiteLLMClient(model="gpt-4o-mini")
        result = await client.complete(
            messages=[Message(role="user", content="do something")],
            tools=[ToolDefinition("my_tool", "desc", {"type": "object", "properties": {}})],
        )
        assert not result.is_final
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "my_tool"
        assert result.tool_calls[0].args == {"key": "value"}


def test_litellm_client_exposes_model_id():
    """LiteLLMClient must expose the model string via a model_id property.

    runtime.py uses getattr(self._llm, 'model_id', None) to record which model
    served each call. Without this property all own_calls entries have model_id=''.
    """
    from everstaff.llm.litellm_client import LiteLLMClient

    client = LiteLLMClient(model="minimax/MiniMax-Text-01")
    assert client.model_id == "minimax/MiniMax-Text-01", (
        f"model_id property missing or wrong. Got: {getattr(client, 'model_id', '<missing>')}"
    )


@pytest.mark.asyncio
async def test_complete_extracts_token_usage():
    """LiteLLMClient.complete() must populate input_tokens and output_tokens from response.usage.

    Without this, all token counts in session metadata are 0 regardless of actual LLM usage.
    """
    from everstaff.llm.litellm_client import LiteLLMClient

    mock_usage = MagicMock()
    mock_usage.prompt_tokens = 100
    mock_usage.completion_tokens = 50

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "done"
    mock_response.choices[0].message.tool_calls = None
    mock_response.usage = mock_usage

    with patch("everstaff.llm.litellm_client.litellm.acompletion", new_callable=AsyncMock) as mock_complete:
        mock_complete.return_value = mock_response
        client = LiteLLMClient(model="gpt-4o-mini")
        result = await client.complete(
            messages=[Message(role="user", content="hi")],
            tools=[],
        )

    assert result.input_tokens == 100, (
        f"input_tokens not extracted from response.usage. Got: {result.input_tokens}"
    )
    assert result.output_tokens == 50, (
        f"output_tokens not extracted from response.usage. Got: {result.output_tokens}"
    )

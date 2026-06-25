import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.llm.client import chat_complete, get_client, LLM_MODEL


def test_llm_model_has_value():
    assert isinstance(LLM_MODEL, str)
    assert len(LLM_MODEL) > 0


@pytest.mark.asyncio
async def test_chat_complete_calls_api():
    fake_message = MagicMock()
    fake_message.content = "Solar panels available from 50W to 550W."
    fake_message.tool_calls = None

    fake_response = MagicMock()
    fake_response.choices = [MagicMock(message=fake_message)]

    with patch("app.llm.client.get_client") as mock_get:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=fake_response)
        mock_get.return_value = mock_client

        messages = [{"role": "user", "content": "What panels do you sell?"}]
        result = await chat_complete(messages)

    assert result.content == "Solar panels available from 50W to 550W."


@pytest.mark.asyncio
async def test_chat_complete_passes_tools():
    fake_message = MagicMock()
    fake_message.content = None
    fake_message.tool_calls = [MagicMock()]

    fake_response = MagicMock()
    fake_response.choices = [MagicMock(message=fake_message)]

    with patch("app.llm.client.get_client") as mock_get:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=fake_response)
        mock_get.return_value = mock_client

        tools = [{"type": "function", "function": {"name": "currency_convert", "parameters": {}}}]
        result = await chat_complete([{"role": "user", "content": "hi"}], tools=tools)
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert "tools" in call_kwargs

import httpx
import pytest
from openai import APIError
from unittest.mock import AsyncMock, patch, MagicMock
from app.llm.client import chat_complete, chat_complete_stream, get_client, LLM_MODEL, LLMUnavailableError


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


def _fake_api_error() -> APIError:
    request = httpx.Request("POST", "https://example.com/v1/chat/completions")
    return APIError("rate limited", request, body=None)


@pytest.mark.asyncio
async def test_chat_complete_wraps_api_error():
    """A transient provider error (timeout/rate-limit) must surface as
    LLMUnavailableError, not bubble up raw and 500 the /api/chat route —
    see the intermittent-500 incident this was added to fix."""
    with patch("app.llm.client.get_client") as mock_get:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=_fake_api_error())
        mock_get.return_value = mock_client

        with pytest.raises(LLMUnavailableError):
            await chat_complete([{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_chat_complete_stream_wraps_api_error():
    with patch("app.llm.client.get_client") as mock_get:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=_fake_api_error())
        mock_get.return_value = mock_client

        with pytest.raises(LLMUnavailableError):
            async for _ in chat_complete_stream([{"role": "user", "content": "hi"}]):
                pass

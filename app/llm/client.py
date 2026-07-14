import os
from dataclasses import dataclass
from typing import AsyncGenerator, Union
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()

LLM_MODEL: str = os.getenv("LLM_MODEL", "google/gemini-3.1-flash-lite")

_client: AsyncOpenAI | None = None


def get_client() -> AsyncOpenAI:
    """Reuse one AsyncOpenAI client for the process so HTTP keep-alive
    connections to OpenRouter are reused instead of a fresh TLS handshake
    on every call."""
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            base_url=os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1"),
            api_key=os.getenv("LLM_API_KEY", ""),
        )
    return _client


async def chat_complete(messages: list[dict], tools: list[dict] | None = None):
    client = get_client()
    kwargs: dict = {"model": LLM_MODEL, "messages": messages}
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    response = await client.chat.completions.create(**kwargs)
    return response.choices[0].message


@dataclass
class PendingToolCall:
    id: str
    name: str
    arguments: str
    extra_content: dict | None = None


async def chat_complete_stream(
    messages: list[dict], tools: list[dict] | None = None
) -> AsyncGenerator[Union[str, list[PendingToolCall]], None]:
    """Streams content tokens as plain strings as they arrive.

    If the model requests tool call(s) instead of (or in addition to) text,
    a single `list[PendingToolCall]` is yielded once the stream ends, after
    any text tokens. This lets a caller stream the common no-tool-call case
    directly instead of paying for a separate blocking call just to check
    whether a tool is needed.
    """
    client = get_client()
    kwargs: dict = {"model": LLM_MODEL, "messages": messages, "stream": True}
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    stream = await client.chat.completions.create(**kwargs)

    pending: dict[int, dict] = {}
    async for chunk in stream:
        delta = chunk.choices[0].delta
        if delta.content:
            yield delta.content
        if delta.tool_calls:
            for tc in delta.tool_calls:
                slot = pending.setdefault(tc.index, {"id": "", "name": "", "arguments": "", "extra_content": None})
                if tc.id:
                    slot["id"] = tc.id
                if tc.function:
                    if tc.function.name:
                        slot["name"] = tc.function.name
                    if tc.function.arguments:
                        slot["arguments"] += tc.function.arguments
                extra_content = getattr(tc, "extra_content", None)
                if extra_content:
                    slot["extra_content"] = extra_content

    if pending:
        yield [PendingToolCall(**slot) for slot in pending.values()]

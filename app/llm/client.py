import os
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()

LLM_MODEL: str = os.getenv("LLM_MODEL", "google/gemini-3.1-flash-lite")


def get_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        base_url=os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1"),
        api_key=os.getenv("LLM_API_KEY", ""),
    )


async def chat_complete(messages: list[dict], tools: list[dict] | None = None):
    client = get_client()
    kwargs: dict = {"model": LLM_MODEL, "messages": messages}
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    response = await client.chat.completions.create(**kwargs)
    return response.choices[0].message

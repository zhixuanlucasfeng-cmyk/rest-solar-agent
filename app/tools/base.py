from abc import ABC, abstractmethod


class BaseTool(ABC):
    name: str
    description: str

    @abstractmethod
    def definition(self) -> dict:
        """Return OpenAI-compatible tool schema for function calling."""
        ...

    @abstractmethod
    async def call(self, params: dict) -> dict:
        """Execute the tool and return a result dict."""
        ...

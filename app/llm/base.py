from abc import ABC, abstractmethod

from app.models import LLMMessage, LLMResponse


class LLMProvider(ABC):
    @abstractmethod
    async def chat(
        self,
        messages: list[LLMMessage],
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        """Send conversation history and return text or tool calls."""
        raise NotImplementedError

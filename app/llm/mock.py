from app.llm.base import LLMProvider
from app.models import LLMMessage, LLMResponse, ToolCall


class MockLLMProvider(LLMProvider):
    """Демонстрационный провайдер для тестов без реальной модели"""

    def __init__(self) -> None:
        self._called_tool = False

    async def chat(
        self,
        messages: list[LLMMessage],
        tools: list[dict] | None = None,
    ) -> LLMResponse:

        has_tool_result = any(
            message.role == "tool"
            for message in messages
        )

        if not self._called_tool and tools:
            self._called_tool = True

            return LLMResponse(
                tool_calls=[
                    ToolCall(
                        name="list_sources",
                        arguments={},
                        call_id="mock-call-1",
                    )
                ],
            )

        if has_tool_result:
            return LLMResponse(
                content=(
                    "Это демонстрационный ответ тестовой модели. "
                    "Инструмент был вызван, его результат передан "
                    "обратно в контекст. Для интеллектуального "
                    "анализа необходимо подключить настоящую LLM."
                )
            )

        question = messages[-1].content if messages else ""

        return LLMResponse(
            content=f"Тестовая модель получила запрос: {question}"
        )

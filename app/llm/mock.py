from app.llm.base import LLMProvider
from app.models import LLMMessage, LLMResponse, ToolCall


class MockLLMProvider(LLMProvider):
    """Демонстрационный провайдер для тестов без реальной модели"""

    async def chat(
        self,
        messages: list[LLMMessage],
        tools: list[dict] | None = None,
    ) -> LLMResponse:

        has_tool_result = any(
            message.role == "tool"
            for message in messages
        )

        if not has_tool_result and tools:
            question = messages[-1].content if messages else ""
            marker = "Источники, указанные пользователем:"
            if marker in question:
                source_id = question.split(marker, 1)[1].split(",", 1)[0].strip()
                if source_id:
                    return LLMResponse(
                        tool_calls=[
                            ToolCall(
                                name="preview_data",
                                arguments={"source_id": source_id, "limit": 12},
                                call_id="mock-preview-source",
                            )
                        ],
                    )
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
                    "Тестовый режим показал первые строки выбранного источника. "
                    "Это предпросмотр фактических данных, а не аналитический "
                    "ответ на вопрос. Для группировок и расчётов подключите настоящую LLM."
                )
            )

        question = messages[-1].content if messages else ""

        return LLMResponse(
            content=f"Тестовая модель получила запрос: {question}"
        )

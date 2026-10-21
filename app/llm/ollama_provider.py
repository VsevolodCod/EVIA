from typing import Any
import asyncio

import httpx

from app.config import Settings
from app.llm.base import LLMProvider, AsyncModel
from app.models import LLMMessage, LLMResponse, ToolCall, ModelTiming


class OllamaModel(AsyncModel):
    """
    Модель для взаимодействия с Ollama API

    :param settings — объект настроек из конфига
    """
    def __init__(
        self,
        settings: Settings
    ) -> None:

        if not settings.llm_model:
            raise ValueError("Ollama model name is required")

        self.model_name = settings.llm_model
        self.url = f"{settings.ollama_base_url.rstrip('/')}/api/chat"
        self.timeout = settings.timeout
        self.think = settings.thinking
        self.num_predict = settings.max_tokens_generate
        self.keep_alive = settings.ollama_keep_alive

    async def generate(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:

        """
        Основной метод взаимодействия с моделью

        :param payload: json с информацией о сообщениях (но может быть не только о сообщениях)
        :return: ответ модели в формате ``json``
        """

        request_data = {
            **payload,
            "model": self.model_name,
            "stream": False,
            "keep_alive": self.keep_alive,
            "options": {
                "num_ctx": 4096,
            },
            "think": self.think,
        }
        if self.num_predict != -1:
            request_data["options"]["num_predict"] = self.num_predict

        async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
            response = await client.post(
                self.url,
                json=request_data,
            )
            response.raise_for_status()
            return response.json()


class OllamaProvider(LLMProvider):
    """
    Провайдер для взаимодействия с моделью Ollama
    """
    def __init__(self, model: AsyncModel) -> None:
        self.model = model

    @staticmethod
    def _serialize_messages(
        messages: list[LLMMessage],
    ) -> list[dict[str, Any]]:

        """
        Подготавливает данные для модели в формате списка строк
        """

        result = []

        for message in messages:
            item: dict[str, Any] = {
                "role": message.role,
                "content": message.content,
            }

            if message.name:
                item["name"] = message.name

            if message.tool_calls:
                item["tool_calls"] = message.tool_calls

            result.append(item)

        return result

    @staticmethod
    def _parse_response(
        data: dict[str, Any],
    ) -> LLMResponse:

        """
        Парсит ответ модели в стандартный формат

        :param data: — данные из модели в формате ``json`` ``dict``
        :return: Обработанный ``LLMResponse``
        """

        message = data.get("message") or {}  # Зачем так написано, я думаю можно data.get("message", {})
        raw_calls = message.get("tool_calls") or []

        calls = []

        for call in raw_calls:
            function = call.get("function") or {}
            arguments = function.get("arguments") or {}

            if not isinstance(arguments, dict):
                arguments = {}

            calls.append(
                ToolCall(
                    name=function.get("name", ""),
                    arguments=arguments,
                )
            )

        return LLMResponse(
            content=message.get("content") or "",
            tool_calls=calls,
            raw_tool_calls=raw_calls,
            finish_reason=data.get("done_reason") if data.get("done") is True else "incomplete",
            timing=ModelTiming(
                model=data.get('model'),
                load_ms=data['load_duration'] / 1_000_000 if data.get('load_duration') is not None else None,
                prompt_ms=data['prompt_eval_duration'] / 1_000_000 if data.get('prompt_eval_duration') is not None else None,
                generation_ms=data['eval_duration'] / 1_000_000 if data.get('eval_duration') is not None else None,
                prompt_tokens=data.get('prompt_eval_count'),
                generated_tokens=data.get('eval_count'),
            ),
        )

    async def chat(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:

        """
        Основной метод для взаимодействия с провайдером

        :param messages: список из ``LLMMessage``
        :param tools: Описания доступных для модели инструментов
        :return: Ответ модели в формате ``LLMResponse``
        """

        payload: dict[str, Any] = {
            "messages": self._serialize_messages(messages),
        }

        if tools:
            payload["tools"] = tools

        data = await self.model.generate(payload)

        return self._parse_response(data)

    async def chat_structured(
        self,
        messages: list[LLMMessage],
        schema: dict[str, Any],
    ) -> LLMResponse:
        """Ask Ollama to enforce the plan schema at generation time."""
        data = await self.model.generate({
            "messages": self._serialize_messages(messages),
            "format": schema,
        })
        return self._parse_response(data)


# Демонстрационный вызов модели с инструментами


# if __name__ == "__main__":
#     def get_weather(city: str) -> str:
#         """Демонстрационный инструмент: возвращает условную погоду."""
#         return f"В городе {city} сейчас +12 °C, облачно."
#
#
#     def calculate(a: float, b: float, operation: str) -> float:
#         """Выполняет простую арифметическую операцию."""
#         if operation == "add":
#             return a + b
#         elif operation == "subtract":
#             return a - b
#         elif operation == "multiply":
#             return a * b
#         elif operation == "divide":
#             if b == 0:
#                 raise ValueError("Деление на ноль")
#             return a / b
#         raise ValueError(f"Неизвестная операция: {operation}")
#
#
#     # Описания, которые увидит модель
#
#     tools = [
#         {
#             "type": "function",
#             "function": {
#                 "name": "get_weather",
#                 "description": "Получить текущую погоду в указанном городе.",
#                 "parameters": {
#                     "type": "object",
#                     "properties": {
#                         "city": {
#                             "type": "string",
#                             "description": "Название города"
#                         }
#                     },
#                     "required": ["city"]
#                 }
#             }
#         },
#         {
#             "type": "function",
#             "function": {
#                 "name": "calculate",
#                 "description": "Вычислить арифметическое выражение с двумя числами.",
#                 "parameters": {
#                     "type": "object",
#                     "properties": {
#                         "a": {"type": "number"},
#                         "b": {"type": "number"},
#                         "operation": {
#                             "type": "string",
#                             "enum": ["add", "subtract", "multiply", "divide"]
#                         }
#                     },
#                     "required": ["a", "b", "operation"]
#                 }
#             }
#         }
#     ]
#
#
#     async def main():
#         model = OllamaModel(
#             model_name="qwen3.5:9b",
#             base_url="http://localhost:11434",
#         )
#
#         provider = OllamaProvider(model)
#
#         messages = [
#             LLMMessage(
#                 role="system",
#                 content=(
#                     "Ты полезный ассистент. "
#                     "Если пользователь просит узнать погоду, используй get_weather. "
#                     "Если просит что-то посчитать, используй calculate."
#                 ),
#             ),
#             LLMMessage(
#                 role="user",
#                 content=(
#                     "Узнай погоду в Санкт-Петербурге, а затем вычисли "
#                     "125 * 8. Используй инструменты."
#                 ),
#             ),
#         ]
#
#         response = await provider.chat(messages, tools=tools)
#
#         print("Ответ модели:", response.content)
#         print("Вызовы инструментов:")
#
#         for call in response.tool_calls:
#             print(f"  Имя: {call.name}")
#             print(f"  Аргументы: {call.arguments}")
#             print(f"  ID: {call.call_id}")
#
#
#     asyncio.run(main())


# async def main():
#     async with httpx.AsyncClient(
#             trust_env=False,
#             timeout=300.0,
#     ) as client:
#         # Проверяем доступность API
#         r = await client.get("http://127.0.0.1:11434/api/tags")
#         print("Tags:", r.status_code, r.text[:500])
#         r.raise_for_status()
#
#         # Проверяем генерацию без провайдера
#         r = await client.post(
#             "http://127.0.0.1:11434/api/chat",
#             json={
#                 "model": "qwen3.5:9b",
#                 "messages": [
#                     {"role": "user", "content": "Ответь одним словом: привет"}
#                 ],
#                 "stream": False,
#                 "think": False,
#                 "options": {"num_predict": 32},
#             },
#         )
#         print("Chat:", r.status_code, r.text[:2000])
#
#
# asyncio.run(main())

import json
from typing import Any

import httpx

from app.llm.base import AsyncModel, LLMProvider
from app.models import LLMMessage, LLMResponse, ToolCall


class OpenAIModel(AsyncModel):
    """
    Модель для взаимодействия с OpenAI API

    :param think: bool — включить ли режим размышления, но тут его нельзя полностью выключить на моделях, где он
    доступен, можно только снизить его влияние или использовать модели, которые ен поддерживают этот режим
    """
    def __init__(
        self,
        base_url: str,
        api_key: str,
        think: bool = False,
        timeout: float = 60.0,
    ) -> None:

        if not api_key:
            raise ValueError("OPENAI_API_KEY is required")

        self.url = f"{base_url.rstrip('/')}/chat/completions"
        self.api_key = api_key
        self.timeout = timeout
        self.think = think

    async def generate(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:

        if not self.think:
            payload["reasoning_effort"] = "low"

        async with httpx.AsyncClient(
            timeout=self.timeout,
        ) as client:
            response = await client.post(
                self.url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            return response.json()


class OpenAIProvider(LLMProvider):
    """
    Провайдер для взаимодействия с моделью OpenAI

    :param model_name: str — название модели. Для OpenAI название модели задается в провайдере, а не в модели
    """
    def __init__(
            self,
            model: AsyncModel,
            model_name: str,
    ) -> None:

        if not model_name:
            raise ValueError("LLM_MODEL is required")

        self.model = model
        self.model_name = model_name

    @staticmethod
    def _serialize_messages(
            messages: list[LLMMessage],
    ) -> list[dict[str, Any]]:

        serialized = []

        for message in messages:
            item: dict[str, Any] = {
                "role": message.role,
                "content": message.content,
            }

            if message.name:
                item["name"] = message.name

            if message.tool_call_id:
                item["tool_call_id"] = message.tool_call_id

            if message.tool_calls:
                item["tool_calls"] = message.tool_calls

            serialized.append(item)

        return serialized

    @staticmethod
    def _parse_response(
            data: dict[str, Any],
    ) -> LLMResponse:

        choices = data.get("choices") or []

        if not choices:
            raise ValueError(
                "OpenAI API returned no choices"
            )

        message = choices[0].get("message") or {}
        raw_calls = message.get("tool_calls") or []

        calls = []

        for call in raw_calls:
            function = call.get("function") or {}
            raw_arguments = function.get("arguments") or "{}"

            try:
                arguments = (
                    json.loads(raw_arguments)
                    if isinstance(raw_arguments, str)
                    else raw_arguments
                )
            except (json.JSONDecodeError, TypeError):
                arguments = {}

            if not isinstance(arguments, dict):
                arguments = {}

            calls.append(
                ToolCall(
                    name=function.get("name", ""),
                    arguments=arguments,
                    call_id=call.get("id"),
                )
            )

        return LLMResponse(
            content=message.get("content") or "",
            tool_calls=calls,
            raw_tool_calls=raw_calls,
        )

    async def chat(
            self,
            messages: list[LLMMessage],
            tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:

        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": self._serialize_messages(messages),
        }

        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        data = await self.model.generate(payload)

        return self._parse_response(data)

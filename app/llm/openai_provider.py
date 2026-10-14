import json

import httpx

from app.llm.base import LLMProvider
from app.models import LLMMessage, LLMResponse, ToolCall


class OpenAIProvider(LLMProvider):
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 60.0,
    ) -> None:
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required")

        if not model:
            raise ValueError("LLM_MODEL is required")

        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    async def chat(
        self,
        messages: list[LLMMessage],
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        serialized_messages = []

        for message in messages:
            item = {
                "role": message.role,
                "content": message.content,
            }

            if message.name:
                item["name"] = message.name

            if message.tool_call_id:
                item["tool_call_id"] = message.tool_call_id

            if message.tool_calls:
                item["tool_calls"] = message.tool_calls

            serialized_messages.append(item)

        payload = {
            "model": self.model,
            "messages": serialized_messages,
        }

        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        async with httpx.AsyncClient(
            timeout=self.timeout
        ) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        choice = data["choices"][0]
        message = choice["message"]
        raw_calls = message.get("tool_calls") or []

        calls = []

        for call in raw_calls:
            function = call.get("function", {})
            raw_arguments = function.get("arguments") or "{}"

            try:
                arguments = (
                    json.loads(raw_arguments)
                    if isinstance(raw_arguments, str)
                    else raw_arguments
                )
            except json.JSONDecodeError:
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

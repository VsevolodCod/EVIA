import httpx

from app.llm.base import LLMProvider
from app.models import LLMMessage, LLMResponse, ToolCall


class OllamaProvider(LLMProvider):
    def __init__(
        self,
        base_url: str,
        model: str,
        timeout: float = 120.0,
    ) -> None:
        if not model:
            raise ValueError("LLM_MODEL is required for Ollama")

        self.base_url = base_url.rstrip("/")
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

            if message.tool_calls:
                item["tool_calls"] = message.tool_calls

            serialized_messages.append(item)

        payload = {
            "model": self.model,
            "messages": serialized_messages,
            "stream": False,
        }

        if tools:
            payload["tools"] = tools

        async with httpx.AsyncClient(
            timeout=self.timeout
        ) as client:
            response = await client.post(
                f"{self.base_url}/api/chat",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        message = data.get("message", {})
        raw_calls = message.get("tool_calls") or []
        calls = []

        for call in raw_calls:
            function = call.get("function", {})
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
        )
    
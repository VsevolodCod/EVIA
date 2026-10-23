import pytest

from app.llm.openai_provider import OpenAIProvider
from app.models import LLMMessage


@pytest.mark.asyncio
async def test_tools_are_available_without_forcing_dashboard_creation():
    class RecordingModel:
        def __init__(self):
            self.payload = None

        async def generate(self, payload):
            self.payload = payload
            return {"choices": [{"message": {"content": "Готово"}, "finish_reason": "stop"}]}

    model = RecordingModel()
    provider = OpenAIProvider(model, "test-model")
    await provider.chat([LLMMessage(role="user", content="Сколько строк?")], tools=[
        {"type": "function", "function": {"name": "query_data"}},
        {"type": "function", "function": {"name": "create_dashboard"}},
    ])
    assert model.payload["tool_choice"] == "auto"

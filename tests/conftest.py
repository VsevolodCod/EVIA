"""Model stubs for tool-protocol tests; calculations use real services."""
import pytest


@pytest.fixture
def scripted_llm():
    class ScriptedLLM:
        def __init__(self, responses):
            self.responses = list(responses)
            self.messages = []

        async def chat(self, messages, tools=None):
            self.messages.append(list(messages))
            assert self.responses, "Unexpected additional inference call"
            response = self.responses.pop(0)
            return response(messages) if callable(response) else response

    return ScriptedLLM

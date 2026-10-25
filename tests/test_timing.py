import json

import httpx
import pytest

from app.agent import AgentRuntime
from app.config import Settings
from app.llm.ollama_provider import OllamaModel, OllamaProvider
from app.llm.openai_provider import OpenAIModel, OpenAIProvider
from app.models import LLMResponse, ToolCall, ToolResult


def test_ollama_nanoseconds_missing_metrics_and_zero_tokens():
    parsed = OllamaProvider._parse_response({'model': 'test', 'message': {'content': 'ok'},
        'done': True, 'done_reason': 'length',
        'total_duration': 50_000_000,
        'load_duration': 2_500_000, 'prompt_eval_duration': 7_000_000,
        'eval_duration': 20_000_000, 'prompt_eval_count': 5, 'eval_count': 0})
    assert parsed.timing.load_ms == 2.5
    assert parsed.timing.provider_total_ms == 50
    assert OllamaProvider._parse_response({'message': {}}).timing.provider_total_ms is None
    assert parsed.timing.prompt_ms == 7
    assert parsed.timing.generation_ms == 20
    assert parsed.timing.generated_tokens == 0
    assert parsed.finish_reason == 'length'
    assert OllamaProvider._parse_response({'message': {}}).timing.load_ms is None


def test_openai_finish_reason_is_preserved():
    parsed = OpenAIProvider._parse_response({
        'choices': [{'finish_reason': 'length', 'message': {'content': 'Оборванный ответ'}}],
    })
    assert parsed.finish_reason == 'length'


def test_provider_missing_finish_metadata_never_looks_complete():
    assert OllamaProvider._parse_response({
        'message': {'content': 'Обрыв'}, 'done': True,
    }).finish_reason not in (None, 'stop')
    assert OllamaProvider._parse_response({
        'message': {'content': 'Обрыв'}, 'done': False, 'done_reason': 'stop',
    }).finish_reason not in (None, 'stop')
    assert OpenAIProvider._parse_response({
        'choices': [{'message': {'content': 'Обрыв'}}],
    }).finish_reason not in (None, 'stop')


@pytest.mark.asyncio
async def test_openai_chat_completion_uses_integer_token_limit(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'test-key')
    monkeypatch.setenv('MAX_TOKENS_G', '256')
    original = httpx.AsyncClient

    def handle(request):
        assert request.url.path == '/v1/chat/completions'
        payload = json.loads(request.content)
        assert payload['max_completion_tokens'] == 256
        assert 'max_output_tokens' not in payload
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': 'ok'}}]})

    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs))
    assert (await OpenAIModel(Settings()).generate({'model': 'test', 'messages': []}))['choices'][0]['finish_reason'] == 'stop'


@pytest.mark.asyncio
async def test_agent_timings_accumulate_across_tool_rounds(monkeypatch):
    clock = iter([0, 1, 3, 4, 5, 6, 9, 10])
    monkeypatch.setattr('app.agent.perf_counter', lambda: next(clock))
    class LLM:
        count = 0
        async def chat(self, *args):
            self.count += 1
            return LLMResponse(tool_calls=[ToolCall(name='test')]) if self.count == 1 else LLMResponse(content='ok')
    class Tools:
        def descriptions(self): return []
        def execute(self, *args): return ToolResult(tool_name='test', ok=True)
    result = await AgentRuntime(LLM(), Tools()).ask('test')
    assert result.timing.elapsed_ms == 10000
    assert result.timing.llm_ms == 5000
    assert result.timing.tools_ms == 1000
    assert [c.elapsed_ms for c in result.timing.calls] == [2000, 3000]
    assert all(c.load_ms is None for c in result.timing.calls)


@pytest.mark.asyncio
async def test_failed_call_logs_elapsed_without_prompt(monkeypatch, caplog):
    clock = iter([0, 1, 3, 4])
    monkeypatch.setattr('app.agent.perf_counter', lambda: next(clock))
    class FailingLLM:
        async def chat(self, *args): raise RuntimeError('outage')
    class Tools:
        def descriptions(self): return []
    with caplog.at_level('INFO'), pytest.raises(RuntimeError):
        await AgentRuntime(FailingLLM(), Tools()).ask('PRIVATE_QUESTION')
    assert 'elapsed_ms=4000.0 llm_ms=2000.0' in caplog.text
    assert 'outcome=error' in caplog.text
    assert 'PRIVATE_QUESTION' not in caplog.text


@pytest.mark.asyncio
async def test_keep_alive_is_sent_without_changing_context_or_token_limit(monkeypatch):
    monkeypatch.setenv('LLM_MODEL', 'synthetic')
    monkeypatch.setenv('OLLAMA_KEEP_ALIVE', '60m')
    monkeypatch.setenv('MAX_TOKENS_G', '768')
    monkeypatch.setenv('THINKING', '0')
    original = httpx.AsyncClient
    def handle(request):
        data = json.loads(request.content)
        assert data['keep_alive'] == '60m'
        assert data['options'] == {'num_ctx': 4096, 'num_predict': 768}
        assert data['think'] is False
        return httpx.Response(200, json={'done': True})
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs))
    assert (await OllamaModel(Settings()).generate({'messages': []}))['done']


@pytest.mark.asyncio
async def test_ollama_structured_chat_sends_json_schema_to_local_model():
    class RecordingModel:
        async def generate(self, payload):
            assert payload["format"]["type"] == "object"
            assert payload["format"]["required"] == ["intent", "sql", "explanation"]
            assert payload["messages"][0]["role"] == "system"
            return {"message": {"content": '{"intent":"count","sql":"SELECT 1","explanation":""}'}}

    from app.models import LLMMessage
    provider = OllamaProvider(RecordingModel())
    response = await provider.chat_structured(
        [LLMMessage(role="system", content="plan")],
        {"type": "object", "required": ["intent", "sql", "explanation"]},
    )
    assert response.content.startswith('{"intent"')


@pytest.mark.asyncio
async def test_ollama_http_error_does_not_print_response_body(monkeypatch, capsys):
    monkeypatch.setenv("LLM_MODEL", "missing")
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(
        transport=httpx.MockTransport(lambda _request: httpx.Response(404, text="private response body")),
        **kwargs,
    ))
    with pytest.raises(httpx.HTTPStatusError):
        await OllamaModel(Settings()).generate({"messages": []})
    assert "private response body" not in capsys.readouterr().out

"""Real SQL/context persistence with scripted model tool choices; no live model."""
import asyncio
import json
from unittest.mock import Mock

import pytest
from httpx import ASGITransport, AsyncClient

from app.agent import AgentRuntime
from app.analysis_context import MAX_CONTEXT_CHARS, MAX_HISTORY_CHARS, bounded_history
from app.chat_manager import ChatManager
from app.db.chat.engine import create_chat_database
from app.models import AnalysisPayload, ChatMessage, LLMResponse, ToolCall
from app.schema_catalog import SchemaCatalog
from app.source_service import SourceService
from app.tools import build_tool_registry

CSV = (b"event_day,revenue,segment\n2024-12-31,900,A\n2025-01-02,10,A\n"
       b"2025-01-20,20,A\n2025-02-01,40,A\n2025-07-01,50,A\n2025-07-20,5,A\n"
       b"2025-01-03,999,B\n2026-01-01,800,A\n")
SQL = "SELECT SUM(revenue) AS total FROM source_typed WHERE segment = 'A' AND event_day >= '2025-01-01' AND event_day < '2026-01-01'"


def request_tool(name, **arguments):
    return LLMResponse(tool_calls=[ToolCall(name=name, arguments=arguments)], finish_reason='tool_calls')


def archive(question, result):
    return [ChatMessage(role='user', content=question), ChatMessage(role='assistant', content=result.answer,
        analysis_payload=AnalysisPayload(version=1, response=result.model_dump(mode='json')))]


@pytest.fixture
def setup(tmp_path):
    catalog = SchemaCatalog(tmp_path / 'catalog.db')
    sources = SourceService(tmp_path / 'data', catalog)
    source = sources.register_csv('sales.csv', CSV)
    yield catalog, sources, source
    catalog.close()


@pytest.mark.asyncio
async def test_four_turn_chain_retains_filters_metric_and_view_across_restart(setup, tmp_path, monkeypatch, scripted_llm):
    from app import main as module
    catalog, sources, source = setup
    llm = scripted_llm([])
    runtime = AgentRuntime(llm, build_tool_registry(catalog, sources), sources=sources)
    spy = Mock(wraps=sources.query)
    monkeypatch.setattr(sources, 'query', spy)
    monkeypatch.setattr(module, 'agent', runtime)
    monkeypatch.setattr(module, 'catalog', catalog)
    monkeypatch.setattr(module, 'source_service', sources)
    monkeypatch.setattr(module.settings, 'chat_db_path', tmp_path / 'chat.db')
    def plan(response):
        llm.responses.extend([response, LLMResponse(content='Расчёт выполнен по выбранному источнику.')])
    async with module.app.router.lifespan_context(module.app), AsyncClient(transport=ASGITransport(app=module.app), base_url='http://test') as client:
        plan(request_tool('query_data', source_id=source.source_id, sql=SQL))
        first = await client.post('/agent/chat', json={'question': 'Выручка за 2025 год для сегмента A', 'source_ids': [source.source_id]})
        assert first.status_code == 200, first.text
        body = first.json()
        assert body['results'][0]['rows'] == [[125]]
        assert len(body['analysis_contexts']) == 1
        chat_id = body['chat_id']
        endpoint = f'/agent/chat?chat_id={chat_id}'

        plan(request_tool('continue_analysis', time_field='event_day', time_grain='month'))
        second = (await client.post(endpoint, json={'question': 'Теперь по месяцам'})).json()
        rows = second['results'][0]['rows']
        assert [(row[0][:10], int(row[1])) for row in rows] == [('2025-01-01', 30), ('2025-02-01', 40), ('2025-07-01', 55)]
        context = second['analysis_contexts'][0]
        assert len(context['filters']) == 3
        assert context['metrics'] == ['SUM(revenue) AS total']
        assert 'MONTH' in context['sql'].upper()
        assert source.source_id in llm.messages[-2][-1].content

        # Fresh DB engine/manager restore context from the persisted JSON payload.
        engine, sessions = create_chat_database(tmp_path / 'chat.db')
        try:
            module.app.state.chat_manager = ChatManager(sessions)
            module.agent = AgentRuntime(llm, build_tool_registry(catalog, sources), sources=sources)
            before_view = spy.call_count
            plan(request_tool('continue_analysis', presentation='bar'))
            third = (await client.post(endpoint, json={'question': 'Покажи столбцами'})).json()
            assert third['results'][0] == second['results'][0]
            assert third['tool_results'][0]['data']['reused_result'] is True
            assert third['analysis_contexts'][0]['presentation'] == 'bar'
            assert spy.call_count == before_view

            plan(request_tool('continue_analysis', add_filters=[{'field': 'event_day', 'date_part': 'month', 'operator': 'ne', 'value': 7}]))
            fourth = (await client.post(endpoint, json={'question': 'Исключи июль'})).json()
            assert [(row[0][:10], int(row[1])) for row in fourth['results'][0]['rows']] == [('2025-01-01', 30), ('2025-02-01', 40)]
            assert sum(int(row[1]) for row in fourth['results'][0]['rows']) == 70
            assert fourth['analysis_contexts'][0]['presentation'] == 'bar'
            assert len(fourth['analysis_contexts'][0]['filters']) == 4
            saved = (await client.get(f'/chats/{chat_id}')).json()
            assert len(saved['messages']) == 8
            assert saved['messages'][-1]['analysis_payload']['response']['analysis_contexts'] == fourth['analysis_contexts']
        finally:
            await engine.dispose()


@pytest.mark.asyncio
async def test_explicit_period_and_metric_changes_preserve_other_filters(setup, scripted_llm):
    catalog, sources, source = setup
    llm = scripted_llm([
        request_tool('query_data', source_id=source.source_id, sql=SQL), LLMResponse(content='125'),
        request_tool('continue_analysis', remove_filter_indexes=[1, 2], add_filters=[
            {'field': 'event_day', 'operator': 'gte', 'value': '2026-01-01'},
            {'field': 'event_day', 'operator': 'lt', 'value': '2027-01-01'}]), LLMResponse(content='800'),
        request_tool('continue_analysis', measure_field='revenue', aggregate='count'), LLMResponse(content='1'),
    ])
    runtime = AgentRuntime(llm, build_tool_registry(catalog, sources), sources=sources)
    first = await runtime.ask('Выручка A за 2025', [source.source_id])
    history = archive('Выручка A за 2025', first)
    second = await runtime.ask('Теперь за 2026 год', [source.source_id], history=history)
    assert second.results[0].rows == [[800]]
    assert "segment = 'A'" in second.analysis_contexts[0].sql
    history += archive('Теперь за 2026 год', second)
    third = await runtime.ask('Вместо суммы количество', [source.source_id], history=history)
    assert third.results[0].rows == [[1]]
    assert third.analysis_contexts[0].metrics == ['COUNT(*) AS value']


@pytest.mark.asyncio
async def test_long_history_has_bounded_text_and_retains_executed_parameters(setup, scripted_llm):
    catalog, sources, source = setup
    llm = scripted_llm([request_tool('query_data', source_id=source.source_id, sql=SQL), LLMResponse(content='125')])
    runtime = AgentRuntime(llm, build_tool_registry(catalog, sources), sources=sources)
    first = await runtime.ask('Выручка A за 2025', [source.source_id])
    history = archive('Выручка A за 2025', first) + [ChatMessage(role='user', content='Длинная реплика ' * 1000) for _ in range(100)]
    llm.responses.extend([request_tool('continue_analysis', time_field='event_day', time_grain='month'), LLMResponse(content='По месяцам')])
    followup = await runtime.ask('По месяцам', [source.source_id], history=history)
    assert sum(int(row[1]) for row in followup.results[0].rows) == 125
    prompt = llm.messages[-2]
    assert sum(len(item.content) for item in prompt[1:-1]) <= MAX_HISTORY_CHARS
    assert len(prompt[-1].content) <= MAX_CONTEXT_CHARS + 500
    assert "segment = 'A'" in prompt[-1].content
    assert len(bounded_history(history)) <= 12


@pytest.mark.asyncio
async def test_snapshot_change_asks_once_then_resets_old_context(setup, scripted_llm):
    catalog, sources, source = setup
    llm = scripted_llm([request_tool('query_data', source_id=source.source_id, sql=SQL), LLMResponse(content='125')])
    runtime = AgentRuntime(llm, build_tool_registry(catalog, sources), sources=sources)
    first = await runtime.ask('Выручка A за 2025', [source.source_id])
    history = archive('Выручка A за 2025', first)
    sources.register_csv('new.csv', b'new_field\n42\n', source_id=source.source_id)
    stale = await runtime.ask('Теперь по месяцам', [source.source_id], history=history)
    assert stale.status == 'clarification' and stale.context_status == 'stale'
    assert stale.steps == 0 and not stale.timing.calls and not stale.results
    history += archive('Теперь по месяцам', stale)
    llm.responses.append(LLMResponse(content='Начнём анализ новых данных.'))
    fresh = await runtime.ask('Начни новый анализ', [source.source_id], history=history)
    assert fresh.context_status == 'none'
    assert 'revenue' not in '\n'.join(item.content for item in llm.messages[-1])


@pytest.mark.asyncio
async def test_parallel_sources_never_share_context_on_same_runtime(setup):
    catalog, sources, first_source = setup
    second_source = sources.register_csv('second.csv', b'revenue\n999\n')
    class Provider:
        async def chat(self, messages, tools=None):
            if messages[-1].role == 'tool':
                return LLMResponse(content='Посчитано')
            source_id = second_source.source_id if second_source.source_id in messages[-1].content else first_source.source_id
            return request_tool('query_data', source_id=source_id, sql='SELECT SUM(revenue) AS total FROM source_typed')
    tools = build_tool_registry(catalog, sources)
    runtime = AgentRuntime(Provider(), tools, sources=sources)
    a, b = await asyncio.gather(runtime.ask('Сумма', [first_source.source_id]), runtime.ask('Сумма', [second_source.source_id]))
    assert a.analysis_contexts[0].source_id == first_source.source_id
    assert b.analysis_contexts[0].source_id == second_source.source_id
    assert b.results[0].rows == [[999]]
    assert 'continue_analysis' not in [item['function']['name'] for item in tools.descriptions()]


@pytest.mark.asyncio
async def test_ambiguous_result_reference_and_invalid_edit_never_recompute(setup, scripted_llm, monkeypatch):
    catalog, sources, source = setup
    llm = scripted_llm([
        LLMResponse(tool_calls=[ToolCall(name='query_data', arguments={'source_id': source.source_id, 'sql': sql})
                               for sql in [SQL, SQL.replace('SUM(revenue)', 'MAX(revenue)')]], finish_reason='tool_calls'),
        LLMResponse(content='Два расчёта'), request_tool('continue_analysis', presentation='bar'), LLMResponse(content='Готово'),
    ])
    runtime = AgentRuntime(llm, build_tool_registry(catalog, sources), sources=sources)
    first = await runtime.ask('Сумма и максимум', [source.source_id])
    assert len(first.analysis_contexts) == 2
    monkeypatch.setattr(sources, 'query', lambda *a, **k: pytest.fail('Ambiguity must not query'))
    ambiguous = await runtime.ask('То же самое столбцами', [source.source_id], history=archive('Сумма и максимум', first))
    assert ambiguous.status == 'clarification' and not ambiguous.results
    assert 'какой' in ambiguous.answer


@pytest.mark.asyncio
@pytest.mark.parametrize('edit', [
    {'time_field': 'segment', 'time_grain': 'month'},
    {'add_filters': [{'field': 'missing', 'operator': 'eq', 'value': 'A'}]},
    {'remove_filter_indexes': [99]},
])
async def test_invalid_continuation_keeps_previous_calculation(setup, scripted_llm, edit):
    catalog, sources, source = setup
    llm = scripted_llm([request_tool('query_data', source_id=source.source_id, sql=SQL), LLMResponse(content='125'),
                        request_tool('continue_analysis', **edit), LLMResponse(content='Нельзя применить')])
    runtime = AgentRuntime(llm, build_tool_registry(catalog, sources), sources=sources)
    first = await runtime.ask('Выручка A за 2025', [source.source_id])
    failed = await runtime.ask('Измени', [source.source_id], history=archive('Выручка A за 2025', first))
    assert failed.status == 'clarification'
    assert not failed.results
    assert failed.analysis_contexts == first.analysis_contexts

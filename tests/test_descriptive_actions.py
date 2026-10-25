import json

import pytest

from app.agent import AgentRuntime
from app.descriptive_actions import descriptive_route
from app.models import ChatMessage, LLMResponse
from app.schema_catalog import SchemaCatalog
from app.source_service import SourceService
from app.tools import build_tool_registry


class Provider:
    def __init__(self, plan=None):
        self.plan = plan
        self.calls = 0

    async def chat(self, messages, tools=None):
        assert self.plan is not None, 'This operation must not call inference'
        self.calls += 1
        return LLMResponse(content=json.dumps(self.plan), finish_reason='stop')


@pytest.fixture
def setup(tmp_path):
    catalog = SchemaCatalog(tmp_path / 'catalog.db')
    sources = SourceService(tmp_path / 'data', catalog)
    source = sources.register_csv('unknown.csv', b'code;segment;amount\n001;A;1,5\n002;A;2\n003;B;3\n003;B;3\n004;;4\n')
    yield sources, source, catalog
    catalog.close()


def runtime(sources, catalog, provider=None):
    return AgentRuntime(provider or Provider(), build_tool_registry(catalog, sources), sources=sources)


@pytest.mark.asyncio
@pytest.mark.parametrize('question', ['какие значения встречаются чаще всего?', 'Покажи наиболее частые значения', 'Какие значения чаще встречаются?', 'А какие значения встречаются чаще всего?', 'А теперь покажи наиболее частые значения'])
async def test_generic_frequency_is_exact_and_states_default_fields(setup, question):
    sources, source, catalog = setup
    response = await runtime(sources, catalog).ask(question, [source.source_id])
    assert response.status == 'answered'
    assert response.analysis.intent == 'frequencies'
    assert response.timing.calls == []
    segment = next(t for t in response.results if t.rows == [[2, 'A'], [2, 'B']])
    assert segment.provenance[0].snapshot_id == source.snapshot_id
    assert 'Поле не указано' in response.answer
    assert 'NULL и пустые строки исключены' in response.answer


@pytest.mark.asyncio
async def test_frequencies_scan_beyond_preview_and_preserve_zeroes(setup):
    sources, _, catalog = setup
    source = sources.register_csv('tail.csv', ('identifier\n' + '001\n' * 500 + '002\n' * 501).encode())
    provider = Provider({'intent': 'frequencies', 'columns': ['identifier'], 'sql': None, 'explanation': 'ignored'})
    response = await runtime(sources, catalog, provider).ask('Посчитай частоты identifier', [source.source_id])
    assert response.results[0].rows == [[501, '002'], [500, '001']]


@pytest.mark.asyncio
async def test_full_duplicates_and_key_duplicates_have_different_grain(setup):
    sources, source, catalog = setup
    answer = await runtime(sources, catalog).ask('Есть ли тут повторяющиеся данные?', [source.source_id])
    assert answer.results[0].rows == [[1, 1]]
    assert 'включая ID' in answer.answer
    provider = Provider({'intent': 'duplicates', 'columns': ['segment'], 'sql': None, 'explanation': ''})
    grouped = await runtime(sources, catalog, provider).ask('Повторы по segment', [source.source_id])
    assert grouped.results[0].rows == [[2, 2]]


@pytest.mark.asyncio
async def test_model_action_rejects_invented_column(setup):
    sources, source, catalog = setup
    provider = Provider({'intent': 'frequencies', 'columns': ['imaginary'], 'sql': None, 'explanation': ''})
    answer = await runtime(sources, catalog, provider).ask('Популярные значения imaginary', [source.source_id])
    assert answer.status == 'error'
    assert answer.error.code == 'QUERY_REJECTED'
    assert answer.results == []


@pytest.mark.asyncio
async def test_empty_dataset_and_all_empty_field_are_not_model_errors(setup):
    sources, _, catalog = setup
    source = sources.register_csv('empty.csv', b'category\n')
    agent = runtime(sources, catalog)
    freq = await agent.ask('Какие значения встречаются чаще всего?', [source.source_id])
    assert freq.status == 'answered' and freq.results[0].rows == []
    duplicates = await agent.ask('Есть ли тут дубликаты?', [source.source_id])
    assert duplicates.results[0].rows == [[0, 0]]


@pytest.mark.parametrize('question', ['Какие значения встречаются чаще всего за июль?', 'Найди дубликаты только за 2024 год',
                                    'Покажи первые 20 строк', 'Какие значения чаще встречаются? Посчитай сумму amount',
                                    'А какие значения встречаются чаще всего за июль?',
                                    'А теперь покажи первые строки только по региону A'])
def test_filtered_queries_are_not_replaced_by_default_actions(question):
    assert descriptive_route(question) is None


@pytest.mark.asyncio
@pytest.mark.parametrize('intent, expected', [('schema', 'source_schema'), ('dataset_overview', 'dataset_overview')])
async def test_model_can_route_unfamiliar_metadata_phrasing(setup, intent, expected):
    sources, source, catalog = setup
    provider = Provider({'intent': intent, 'sql': None, 'columns': [], 'explanation': 'invented 999 rows'})
    answer = await runtime(sources, catalog, provider).ask('Познакомь меня с содержимым выбранного файла', [source.source_id])
    assert answer.status == 'answered'
    assert answer.analysis.intent == expected
    assert '999' not in answer.answer
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_frequency_results_never_mix_concurrent_snapshots(setup, monkeypatch):
    sources, source, catalog = setup
    original = sources.query
    def reimport_before_query(*args, **kwargs):
        sources.register_csv('changed.csv', b'code;segment;amount\n009;Z;90\n', source_id=source.source_id)
        return original(*args, **kwargs)
    monkeypatch.setattr(sources, 'query', reimport_before_query)
    answer = await runtime(sources, catalog).ask('Какие значения встречаются чаще всего?', [source.source_id])
    assert answer.status == 'error'
    assert answer.results == []


def test_boolean_filters_preserve_external_read_protection(setup):
    from app.safe_sql import SafeQueryError
    sources, source, _ = setup
    answer = sources.query(source.source_id,
        "SELECT code FROM source WHERE (segment = 'A' OR segment = 'B') AND code = '001'")
    assert answer.rows == [['001']]
    with pytest.raises(SafeQueryError):
        sources.query(source.source_id,
            "SELECT code FROM source WHERE code = '001' OR EXISTS (SELECT * FROM read_csv_auto('/etc/passwd'))")


@pytest.mark.asyncio
async def test_sequence_keeps_source_and_results_after_model_followup(setup):
    sources, source, catalog = setup
    provider = Provider({'intent': 'frequencies', 'columns': ['segment'], 'sql': None, 'explanation': ''})
    agent = runtime(sources, catalog, provider)
    history = []
    for question in ['Что передо мной?', 'Какие значения встречаются чаще всего?',
                     'Есть ли тут повторяющиеся данные?', 'А теперь частоты segment']:
        answer = await agent.ask(question, [source.source_id], history=history)
        assert answer.status == 'answered'
        assert all(p.source_id == source.source_id for r in answer.results for p in r.provenance)
        history.extend([ChatMessage(role='user', content=question), ChatMessage(role='assistant', content=answer.answer)])
    assert answer.results[0].rows == [[2, 'A'], [2, 'B']]
    assert provider.calls == 1

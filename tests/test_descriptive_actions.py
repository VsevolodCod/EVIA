"""Numerical calculator tests; tool-loop integration is tested separately."""

import pytest

from app.descriptive_actions import descriptive_answer, descriptive_route
from app.models import AgentTiming
from app.safe_sql import SafeQueryError
from app.schema_catalog import SchemaCatalog
from app.source_service import SourceService


@pytest.fixture
def setup(tmp_path):
    catalog = SchemaCatalog(tmp_path / 'catalog.db')
    sources = SourceService(tmp_path / 'data', catalog)
    source = sources.register_csv('unknown.csv', b'code;segment;amount\n001;A;1,5\n002;A;2\n003;B;3\n003;B;3\n004;;4\n')
    yield sources, source, catalog
    catalog.close()


def calculate(sources, source_id, intent, columns=None):
    return descriptive_answer(sources, intent, columns or [], source_id,
                              sources.get_schema(source_id), AgentTiming(), "test")


@pytest.mark.asyncio
@pytest.mark.parametrize('question', ['какие значения встречаются чаще всего?', 'Покажи наиболее частые значения', 'Какие значения чаще встречаются?', 'А какие значения встречаются чаще всего?', 'А теперь покажи наиболее частые значения'])
async def test_generic_frequency_is_exact_and_states_default_fields(setup, question):
    sources, source, catalog = setup
    assert descriptive_route(question) == 'frequencies'
    response = calculate(sources, source.source_id, 'frequencies')
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
    response = calculate(sources, source.source_id, 'frequencies', ['identifier'])
    assert response.results[0].rows == [[501, '002'], [500, '001']]


@pytest.mark.asyncio
async def test_full_duplicates_and_key_duplicates_have_different_grain(setup):
    sources, source, catalog = setup
    answer = calculate(sources, source.source_id, 'duplicates')
    assert answer.results[0].rows == [[1, 1]]
    assert 'включая ID' in answer.answer
    grouped = calculate(sources, source.source_id, 'duplicates', ['segment'])
    assert grouped.results[0].rows == [[2, 2]]


@pytest.mark.asyncio
async def test_model_action_rejects_invented_column(setup):
    sources, source, catalog = setup
    with pytest.raises(SafeQueryError, match='QUERY_REJECTED'):
        calculate(sources, source.source_id, 'frequencies', ['imaginary'])


@pytest.mark.asyncio
async def test_empty_dataset_and_all_empty_field_are_not_model_errors(setup):
    sources, _, catalog = setup
    source = sources.register_csv('empty.csv', b'category\n')
    freq = calculate(sources, source.source_id, 'frequencies')
    assert freq.status == 'answered' and freq.results[0].rows == []
    duplicates = calculate(sources, source.source_id, 'duplicates')
    assert duplicates.results[0].rows == [[0, 0]]


@pytest.mark.asyncio
async def test_outliers_use_iqr_thresholds_and_never_claim_a_cause(setup):
    sources, _, catalog = setup
    source = sources.register_csv(
        "outliers.csv",
        b"month;revenue\nJan;1\nFeb;2\nMar;2\nApr;3\nMay;100\n",
    )

    assert descriptive_route("Есть ли здесь аномалии?") == "outliers"
    response = calculate(sources, source.source_id, 'outliers')

    assert response.status == "answered"
    assert response.analysis.intent == "outliers"
    assert response.timing.calls == []
    assert "IQR" in response.answer
    assert "не удалены" in response.answer
    assert any(float(row[0]) == 100 for result in response.results for row in result.rows)


@pytest.mark.asyncio
async def test_outliers_explain_when_fewer_than_four_numeric_values_are_available(setup):
    sources, _, catalog = setup
    source = sources.register_csv("small-sample.csv", b"revenue\n1\n2\n3\n")

    response = calculate(sources, source.source_id, 'outliers')

    assert response.status == "answered"
    assert "минимум 4" in response.answer
    assert "найдено 3" in response.answer
    assert len(response.results) == 1


@pytest.mark.asyncio
async def test_outliers_explain_zero_iqr_for_a_constant_series(setup):
    sources, _, catalog = setup
    source = sources.register_csv("constant.csv", b"revenue\n5\n5\n5\n5\n")

    response = calculate(sources, source.source_id, 'outliers')

    assert response.status == "answered"
    assert "IQR равен нулю" in response.answer
    assert len(response.results) == 1


@pytest.mark.asyncio
async def test_zero_iqr_with_rare_different_value_does_not_claim_all_values_are_equal(setup):
    sources, _, catalog = setup
    source = sources.register_csv("rare-value.csv", b"revenue\n5\n5\n5\n5\n100\n")

    response = calculate(sources, source.source_id, 'outliers')

    assert response.status == "answered"
    assert "IQR равен нулю" in response.answer
    assert "есть отличающиеся значения" in response.answer
    assert "все корректные значения находятся на одном уровне" not in response.answer
    assert len(response.results) == 1


@pytest.mark.asyncio
async def test_outliers_compare_heterogeneous_segments_separately(setup):
    sources, _, catalog = setup
    source = sources.register_csv(
        "segmented.csv",
        b"segment;revenue\nA;1\nA;2\nA;2\nA;3\nA;100\n"
        b"B;100\nB;100\nB;100\nB;100\nB;100\n"
        b"C;1\nC;1\nC;50\n;1000\n",
    )

    response = calculate(sources, source.source_id, 'outliers', ['revenue', 'segment'])

    assert response.status == "answered"
    assert "Группа сравнения — значения внутри поля «segment»" in response.answer
    assert "Пустые значения группы исключены" in response.answer
    assert "Группа «B»: IQR равен нулю" in response.answer
    assert "Группа «C»: меньше 4" in response.answer
    assert "не удалены" in response.answer
    assert any(row[0] == "A" and float(row[1]) == 100 for row in response.results[-1].rows)
    assert all(row[0] == "A" for row in response.results[-1].rows)


@pytest.mark.asyncio
async def test_grouped_outliers_do_not_silently_analyze_only_first_twenty_groups(setup):
    sources, _, catalog = setup
    rows = ["segment;revenue"] + [f"G{index:02d};{value}" for index in range(21) for value in (1, 2, 3, 4)]
    source = sources.register_csv("many-groups.csv", ("\n".join(rows) + "\n").encode())

    response = calculate(sources, source.source_id, 'outliers', ['revenue', 'segment'])

    assert response.status == "answered"
    assert "больше 20 групп" in response.answer
    assert "Анализ кандидатов не выполнялся" in response.answer
    assert len(response.results) == 1


@pytest.mark.parametrize('question', ['Какие значения встречаются чаще всего за июль?', 'Найди дубликаты только за 2024 год',
                                    'Покажи первые 20 строк', 'Какие значения чаще встречаются? Посчитай сумму amount',
                                    'А какие значения встречаются чаще всего за июль?',
                                    'А теперь покажи первые строки только по региону A'])
def test_filtered_queries_are_not_replaced_by_default_actions(question):
    assert descriptive_route(question) is None


@pytest.mark.asyncio
async def test_frequency_results_never_mix_concurrent_snapshots(setup, monkeypatch):
    sources, source, catalog = setup
    original = sources.query
    def reimport_before_query(*args, **kwargs):
        sources.register_csv('changed.csv', b'code;segment;amount\n009;Z;90\n', source_id=source.source_id)
        return original(*args, **kwargs)
    monkeypatch.setattr(sources, 'query', reimport_before_query)
    with pytest.raises(SafeQueryError, match='QUERY_REJECTED'):
        calculate(sources, source.source_id, 'frequencies')


def test_boolean_filters_preserve_external_read_protection(setup):
    from app.safe_sql import SafeQueryError
    sources, source, _ = setup
    answer = sources.query(source.source_id,
        "SELECT code FROM source WHERE (segment = 'A' OR segment = 'B') AND code = '001'")
    assert answer.rows == [['001']]
    with pytest.raises(SafeQueryError):
        sources.query(source.source_id,
            "SELECT code FROM source WHERE code = '001' OR EXISTS (SELECT * FROM read_csv_auto('/etc/passwd'))")

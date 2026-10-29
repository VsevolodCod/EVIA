"""Agent plan -> real CSV calculations -> persisted definitions -> rebuild.

Only the LLM is a stub. Expected numbers are hand computed, not inferred from
the generated SQL. These tests run in CI without Ollama or provider secrets.
"""
import json

import pytest
from pydantic import ValidationError

from app.agent import AgentRuntime
from app.charts.executor import ChartExecutor
from app.charts.implementations.line import LineImplementation
from app.charts.models import LineCard, LineXAxis
from app.charts.query_planner import QueryPlanner
from app.charts.repositories import ChartRepository, DashboardRepository
from app.models import LLMResponse, ToolCall
from app.schema_catalog import SchemaCatalog
from app.source_service import SourceService
from app.tools.registration import build_tool_registry


class ToolDashboardLLM:
    """Script only tool choice; registry/executor/storage do real work."""
    def __init__(self, plan, source_id):
        self.plan = plan
        self.source_id = source_id
        self.calls = 0

    async def chat(self, messages, tools=None):
        self.calls += 1
        if self.calls == 1:
            definitions = []
            for card in self.plan['cards']:
                definition = {'type': card['type'], 'title': card['title'], 'filters': [
                    {**item, 'field': {'source_id': self.source_id, 'field': item['field']}}
                    for item in self.plan['filters']
                ]}
                ref = lambda field: {'source_id': self.source_id, 'field': field}
                if card['type'] == 'kpi':
                    definition.update(field=ref(card['field']), aggregate=card['aggregate'])
                elif card['type'] in {'line', 'bar'}:
                    definition.update(x={**ref(card['x']),
                        'type': 'temporal' if card.get('time_grain') else 'category',
                        'time_grain': card.get('time_grain')},
                        y={**ref(card['y']), 'aggregate': card['aggregate']})
                elif card['type'] == 'scatter':
                    definition.update(x=ref(card['x']), y=ref(card['y']))
                else:
                    definition['fields'] = [ref(field) for field in card['fields']]
                definitions.append(definition)
            return LLMResponse(tool_calls=[ToolCall(name='build_chart', arguments={'definition': definition})
                                           for definition in definitions], finish_reason='tool_calls')
        if self.calls == 2:
            built = [json.loads(m.content)['data'] for m in messages if m.role == 'tool']
            assert all(item['success'] for item in built)
            return LLMResponse(tool_calls=[ToolCall(name='compose_dashboard', arguments={
                'title': self.plan['title'], 'chart_ids': [item['chart_id'] for item in built],
            })], finish_reason='tool_calls')
        return LLMResponse(content='Панель создана по вычисленным данным.')


def make_plan(date="event_day", value="amount", segment="segment"):
    return {
        "title": "A, 2025, кварталы",
        "filters": [
            {"field": segment, "operator": "eq", "value": "A"},
            {"field": date, "operator": "gte", "value": "2025-01-01"},
            {"field": date, "operator": "lt", "value": "2026-01-01"},
        ],
        "cards": [
            {"type": "kpi", "title": "Сумма", "field": value, "aggregate": "sum"},
            {"type": "line", "title": "Кварталы", "x": date, "y": value,
             "aggregate": "sum", "time_grain": "quarter"},
        ],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("names", [
    ("event_day", "amount", "segment"),
    ("service_date", "duration", "team"),
    ("Дата события", "Стоимость", "Группа"),
])
async def test_filtered_quarters_match_oracle_and_survive_restart(tmp_path, names):
    # Adjacent years and another segment are deliberate exclusion traps.
    csv = (";".join(names) + "\n"
           "2024-12-31;900;A\n2025-01-01;10;A\n2025-02-20;20;A\n"
           "2025-03-31;30;A\n2025-04-01;40;A\n2025-07-01;-5;A\n"
           "2025-12-31;50;A\n2026-01-01;800;A\n2025-01-02;700;B\n"
           ";600;A\n")
    catalog = SchemaCatalog(tmp_path / "catalog.db")
    sources = SourceService(tmp_path / "data", catalog)
    source = sources.register_csv("unknown.csv", csv.encode())
    llm = ToolDashboardLLM(make_plan(*names), source.source_id)
    try:
        result = await AgentRuntime(llm, build_tool_registry(catalog, sources), sources=sources).ask(
            f"Создай дашборд суммы {names[1]} для {names[2]} A за 2025 год по кварталам {names[0]}",
            [source.source_id],
        )
        assert result.status == "answered", result
        dashboard = result.tool_results[-1].data["dashboard"]
        assert dashboard["id"]
        built = [item.data for item in result.tool_results if item.tool_name == "build_chart"]
        kpi, line = [{"data": item["result"], "definition": item["definition"]} for item in built]
        assert float(kpi["data"]["value"]) == 145
        assert [(p["x"][:10], float(p["y"])) for p in line["data"]["points"]] == [
            ("2025-01-01", 60), ("2025-04-01", 40), ("2025-07-01", -5), ("2025-10-01", 50),
        ]
        assert line["definition"]["x"]["time_grain"] == "quarter"
        for card in (kpi, line):
            assert len(card["definition"]["filters"]) == 3
            assert card["data"]["provenance"][0]["source_id"] == source.source_id
            assert all(f["field"]["source_id"] == source.source_id for f in card["definition"]["filters"])
        assert llm.calls == 3
    finally:
        catalog.close()

    # Reopen the database and service, not just the in-memory object.
    reopened = SchemaCatalog(tmp_path / "catalog.db")
    try:
        sources = SourceService(tmp_path / "data", reopened)
        charts = ChartRepository(reopened.session_factory)
        saved = DashboardRepository(reopened.session_factory).get_by_id(dashboard["id"])
        executor = ChartExecutor.build_executor(sources, reopened, charts)
        refs = sorted(saved.charts, key=lambda ref: ref.position)
        assert float(executor.execute(refs[0].chart_id)["value"]) == 145
        assert executor.execute(refs[1].chart_id)["points"] == line["data"]["points"]
    finally:
        reopened.close()


@pytest.mark.parametrize("fault", ["unknown_field", "bad_operator", "bad_grain", "non_date_axis"])
def test_invalid_chart_conditions_do_not_leave_persisted_artifacts(tmp_path, fault):
    catalog = SchemaCatalog(tmp_path / "catalog.db")
    sources = SourceService(tmp_path / "data", catalog)
    source = sources.register_csv("sales.csv", b"event_day,amount,segment\n2025-01-01,10,A\n")
    definition = {
        "type": "line", "title": "Период",
        "x": {"source_id": source.source_id, "field": "event_day", "type": "temporal", "time_grain": "quarter"},
        "y": {"source_id": source.source_id, "field": "amount", "aggregate": "sum"},
        "filters": [{"field": {"source_id": source.source_id, "field": "segment"}, "operator": "eq", "value": "A"}],
    }
    if fault == "unknown_field": definition["filters"][0]["field"]["field"] = "missing"
    elif fault == "bad_operator": definition["filters"][0]["operator"] = "execute_sql"
    elif fault == "bad_grain": definition["x"]["time_grain"] = "quarter'); DROP TABLE source; --"
    else: definition["x"]["field"] = "segment"
    try:
        result = build_tool_registry(catalog, sources).execute("build_chart", {"definition": definition})
        assert not result.ok or not result.data["success"]
        assert ChartRepository(catalog.session_factory).list_all() == []
    finally:
        catalog.close()


@pytest.mark.parametrize("grain", ["day", "week", "month", "quarter", "year"])
def test_temporal_buckets_are_real_calendar_groups(tmp_path, grain):
    catalog = SchemaCatalog(tmp_path / "catalog.db")
    sources = SourceService(tmp_path / "data", catalog)
    source = sources.register_csv("dates.csv", (
        "event_day,amount\n2024-01-02,1\n2025-01-02,2\n2025-01-03,3\n2025-04-01,4\n"
    ).encode())
    expected = {
        "day": [("2024-01-02", 1), ("2025-01-02", 2), ("2025-01-03", 3), ("2025-04-01", 4)],
        "week": [("2024-01-01", 1), ("2024-12-30", 5), ("2025-03-31", 4)],
        "month": [("2024-01-01", 1), ("2025-01-01", 5), ("2025-04-01", 4)],
        "quarter": [("2024-01-01", 1), ("2025-01-01", 5), ("2025-04-01", 4)],
        "year": [("2024-01-01", 1), ("2025-01-01", 9)],
    }
    try:
        definition = {
            "type": "line", "title": "Calendar",
            "x": {"source_id": source.source_id, "field": "event_day", "type": "temporal", "time_grain": grain},
            "y": {"source_id": source.source_id, "field": "amount", "aggregate": "sum"},
        }
        # Exercise the calculation directly so CI reports the underlying
        # validation/SQL exception instead of build_chart's public fallback.
        LineImplementation(sources, QueryPlanner(catalog)).execute(LineCard.model_validate(definition), [])
        result = build_tool_registry(catalog, sources).execute("build_chart", {"definition": definition})
        assert result.ok and result.data["success"], result
        assert [(p["x"][:10], float(p["y"])) for p in result.data["result"]["points"]] == expected[grain]
    finally:
        catalog.close()


def test_time_grain_is_not_arbitrary_sql_or_a_category_transform():
    for axis in [
        {"type": "temporal", "time_grain": "quarter'); DROP TABLE source; --"},
        {"type": "category", "time_grain": "month"},
    ]:
        with pytest.raises(ValidationError):
            LineXAxis(source_id="selected", field="x", **axis)


def test_build_tool_persists_extra_filters_and_rebuild_does_not_broaden_scope(tmp_path):
    catalog = SchemaCatalog(tmp_path / "catalog.db")
    sources = SourceService(tmp_path / "data", catalog)
    source = sources.register_csv("sales.csv", b"id,amount\n001,10\n002,20\n")
    try:
        result = build_tool_registry(catalog, sources).execute("build_chart", {
            "definition": {"type": "kpi", "title": "001", "aggregate": "sum",
                           "field": {"source_id": source.source_id, "field": "amount"}},
            "filters": [{"field": {"source_id": source.source_id, "field": "id"},
                         "operator": "eq", "value": "001"}],
        })
        assert result.ok and result.data["success"], result
        assert float(result.data["result"]["value"]) == 10
        assert result.data["definition"]["filters"][0]["value"] == "001"
        executor = ChartExecutor.build_executor(sources, catalog, ChartRepository(catalog.session_factory))
        assert float(executor.execute(result.data["chart_id"])["value"]) == 10
    finally:
        catalog.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,csv,card,expected", [
    ("bar", "category,amount\nA,10\nA,20\nB,5\n",
     {"type": "bar", "title": "По категории", "x": "category", "y": "amount", "aggregate": "sum"},
     [{"x": "A", "y": 30}, {"x": "B", "y": 5}]),
    ("scatter", "revenue,cost\n10,5\n10,5\n20,8\n",
     {"type": "scatter", "title": "Связь показателей", "x": "revenue", "y": "cost"},
     [{"x": 10, "y": 5}, {"x": 10, "y": 5}, {"x": 20, "y": 8}]),
    ("table", "category,note\nA,ok\nB,review\n",
     {"type": "table", "title": "Строки", "fields": ["category", "note"]},
     [{"category": "A", "note": "ok"}, {"category": "B", "note": "review"}]),
])
async def test_agent_builds_requested_chart_type_and_reopens_it(tmp_path, kind, csv, card, expected):
    catalog = SchemaCatalog(tmp_path / "catalog.db")
    sources = SourceService(tmp_path / "data", catalog)
    source = sources.register_csv("chart.csv", csv.encode())
    llm = ToolDashboardLLM({"title": "Панель", "filters": [], "cards": [card]}, source.source_id)
    try:
        response = await AgentRuntime(llm, build_tool_registry(catalog, sources), sources=sources).ask(
            "Создай дашборд с графиком или таблицей по этим полям", [source.source_id],
        )
        assert response.status == "answered", response
        built = response.tool_results[0].data
        assert built['success']
        assert built['definition']['type'] == kind
        payload = built['result']
        assert payload["points" if kind != "table" else "rows"] == expected
        chart_id = built["chart_id"]
        executor = ChartExecutor.build_executor(sources, catalog, ChartRepository(catalog.session_factory))
        assert executor.execute(chart_id)["points" if kind != "table" else "rows"] == expected
    finally:
        catalog.close()

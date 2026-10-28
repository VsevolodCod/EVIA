"""Agent plan -> real CSV calculations -> persisted definitions -> rebuild.

Only the LLM is a stub. Expected numbers are hand computed, not inferred from
the generated SQL. These tests run in CI without Ollama or provider secrets.
"""
import json

import pytest
import sqlglot
from pydantic import ValidationError
from sqlglot import exp

from app.agent import AgentRuntime
from app.charts.executor import ChartExecutor
from app.charts.implementations.line import LineImplementation
from app.charts.models import LineCard, LineXAxis
from app.charts.query_planner import QueryPlanner
from app.charts.repositories import ChartRepository, DashboardRepository
from app.dashboard_query_agent import DashboardDraft
from app.models import LLMResponse
from app.schema_catalog import SchemaCatalog
from app.source_service import SourceService
from app.tools.registration import build_tool_registry


class PlanLLM:
    def __init__(self, plan):
        self.plan = plan
        self.calls = 0

    async def chat_structured(self, messages, schema):
        self.calls += 1
        return LLMResponse(content=json.dumps(self.plan), finish_reason="stop")


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
    llm = PlanLLM(make_plan(*names))
    try:
        result = await AgentRuntime(llm, build_tool_registry(catalog, sources), sources=sources).ask(
            f"Создай дашборд суммы {names[1]} для {names[2]} A за 2025 год по кварталам {names[0]}",
            [source.source_id],
        )
        assert result.status == "answered", result
        dashboard = result.tool_results[-1].data
        assert dashboard["id"]
        kpi, line = dashboard["cards"]
        assert float(kpi["data"]["value"]) == 145
        assert [(p["x"][:10], float(p["y"])) for p in line["data"]["points"]] == [
            ("2025-01-01", 60), ("2025-04-01", 40), ("2025-07-01", -5), ("2025-10-01", 50),
        ]
        assert line["definition"]["x"]["time_grain"] == "quarter"
        for card in (kpi, line):
            assert len(card["definition"]["filters"]) == 3
            assert card["data"]["provenance"][0]["source_id"] == source.source_id
            assert all(f["field"]["source_id"] == source.source_id for f in card["definition"]["filters"])
        assert llm.calls == 1
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


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["missing_filters", "unknown_filter", "bad_operator", "bad_json", "truncated"])
async def test_incomplete_plan_never_falls_back_to_unfiltered_dashboard(tmp_path, fault):
    catalog = SchemaCatalog(tmp_path / "catalog.db")
    sources = SourceService(tmp_path / "data", catalog)
    source = sources.register_csv("sales.csv", b"event_day,amount,segment\n2025-01-01,10,A\n")
    plan = make_plan()
    if fault == "missing_filters":
        del plan["filters"]
    elif fault == "unknown_filter":
        plan["filters"][0]["field"] = "not_in_schema"
    elif fault == "bad_operator":
        plan["filters"][0]["operator"] = "execute_sql"
    llm = PlanLLM(plan)
    if fault in {"bad_json", "truncated"}:
        async def invalid(*args):
            return LLMResponse(content="not JSON" if fault == "bad_json" else json.dumps(plan),
                               finish_reason="stop" if fault == "bad_json" else "length")
        llm.chat_structured = invalid
    registry = build_tool_registry(catalog, sources)
    def never_execute(*args):
        raise AssertionError("No artifacts may be built from an invalid plan")
    registry.execute = never_execute
    try:
        result = await AgentRuntime(llm, registry, sources=sources).ask(
            "Дашборд по кварталам только для A за 2025 год", [source.source_id],
        )
        assert result.status == "clarification"
        assert result.tool_results == []
        assert result.answer_kind != "computed"
    finally:
        catalog.close()


@pytest.mark.asyncio
async def test_unsupported_condition_returns_specific_clarification_without_tools(tmp_path):
    catalog = SchemaCatalog(tmp_path / "catalog.db")
    sources = SourceService(tmp_path / "data", catalog)
    source = sources.register_csv("sales.csv", b"amount\n10\n")
    llm = PlanLLM({"title": "Уточнение", "filters": [], "cards": [],
                   "clarification": "В источнике нет поля даты. За какой период считать без даты?"})
    registry = build_tool_registry(catalog, sources)
    registry.execute = lambda *args: pytest.fail("Clarification must not execute tools")
    try:
        result = await AgentRuntime(llm, registry, sources=sources).ask(
            "Создай дашборд amount за сегодня", [source.source_id],
        )
        assert result.status == "clarification"
        assert "нет поля даты" in result.answer
        assert not result.tool_results
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
        parsed = sqlglot.parse_one(
            f"SELECT DATE_TRUNC('{grain}', \"event_day\") FROM source_typed",
            read="duckdb",
        )
        names = [(type(function).__name__, function.sql_name()) for function in parsed.find_all(exp.Func)]
        assert all(name.upper() == "DATE_TRUNC" for _, name in names), names
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


def test_filter_values_and_conditions_are_strict():
    for condition in [
        {"field": "amount", "operator": "eq", "value": [10, 20]},
        {"field": "amount", "operator": "eq", "value": {"sql": "SELECT 1"}},
        {"field": "amount", "operator": "gt", "value": float("inf")},
        {"field": "amount", "operator": "is_null", "value": 1},
    ]:
        plan = make_plan()
        plan["filters"] = [condition]
        with pytest.raises(ValidationError):
            DashboardDraft.model_validate(plan)


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

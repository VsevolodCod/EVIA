import json

import pytest

from app.agent import AgentRuntime
from app.charts.models import ChartModel
from app.charts.repositories import ChartRepository, DashboardRepository
from app.models import LLMResponse, ToolCall
from app.schema_catalog import SchemaCatalog
from app.source_service import SourceService
from app.tools import build_tool_registry


@pytest.mark.asyncio
@pytest.mark.parametrize("nested", [False, True])
async def test_model_cannot_expand_selected_source_scope(tmp_path, scripted_llm, nested):
    catalog = SchemaCatalog(tmp_path / "catalog.db")
    sources = SourceService(tmp_path / "data", catalog)
    selected = sources.register_csv("a.csv", b"amount\n10\n")
    other = sources.register_csv("b.csv", b"amount\n999\n")
    args = {"source_id": other.source_id, "sql": "SELECT * FROM source"}
    tool = "query_data"
    if nested:
        tool = "build_chart"
        args = {"definition": {"type": "kpi", "title": "Other", "aggregate": "sum",
                               "field": {"source_id": other.source_id, "field": "amount"}}}
    llm = scripted_llm([
        LLMResponse(tool_calls=[ToolCall(name=tool, arguments=args)], finish_reason="tool_calls"),
        LLMResponse(content="Запрошен другой источник; выберите его явно."),
    ])
    try:
        result = await AgentRuntime(llm, build_tool_registry(catalog, sources), sources=sources).ask(
            "Проанализируй выбранный файл", [selected.source_id],
        )
        assert result.tool_results[0].error == "SOURCE_SCOPE_VIOLATION"
        assert not result.results
        assert ChartRepository(catalog.session_factory).list_all() == []
        assert "999" not in json.dumps(result.model_dump(mode="json"))
    finally:
        catalog.close()


@pytest.mark.asyncio
async def test_step_limit_is_an_error_and_retains_actual_tool_results(tmp_path, scripted_llm):
    catalog = SchemaCatalog(tmp_path / "catalog.db")
    sources = SourceService(tmp_path / "data", catalog)
    llm = scripted_llm([LLMResponse(tool_calls=[ToolCall(name="list_sources")], finish_reason="tool_calls")])
    try:
        result = await AgentRuntime(llm, build_tool_registry(catalog, sources), max_steps=1).ask("Обзор")
        assert result.status == "error"
        assert result.error.code == "QUERY_REJECTED"
        assert result.tool_results[0].ok
        assert result.error.retryable
    finally:
        catalog.close()


@pytest.mark.asyncio
async def test_truncated_tool_arguments_are_not_executed(tmp_path, scripted_llm):
    catalog = SchemaCatalog(tmp_path / "catalog.db")
    sources = SourceService(tmp_path / "data", catalog)
    llm = scripted_llm([LLMResponse(content="", tool_calls=[ToolCall(name="list_sources")], finish_reason="length")])
    try:
        result = await AgentRuntime(llm, build_tool_registry(catalog, sources)).ask("Обзор")
        assert result.status == "error"
        assert result.error.code == "MODEL_OUTPUT_INCOMPLETE"
        assert result.tool_results == []
    finally:
        catalog.close()


def test_chart_id_accepts_legacy_input_and_keeps_current_wire_contract():
    definition = {"type": "kpi", "title": "Total", "field": {"source_id": "s", "field": "x"}, "aggregate": "sum"}
    old = ChartModel(id="chart-1", definition=definition)
    new = ChartModel(chart_id="chart-1", definition=definition)
    assert old == new
    assert old.id == old.chart_id == "chart-1"
    assert old.model_dump()["chart_id"] == "chart-1"
    assert "id" not in old.model_dump()


def test_factory_allows_explicit_dependency_injection(tmp_path):
    from app.charts.engine import DashboardEngine
    from app.charts.executor import ChartExecutor
    catalog = SchemaCatalog(tmp_path / "catalog.db")
    sources = SourceService(tmp_path / "data", catalog)
    charts = ChartRepository(catalog.session_factory)
    dashboards = DashboardRepository(catalog.session_factory)
    try:
        registry = build_tool_registry(catalog, sources, DashboardEngine(charts, dashboards),
                                       ChartExecutor.build_executor(sources, catalog, charts), charts)
        assert registry.execute("list_sources", {}).ok
    finally:
        catalog.close()

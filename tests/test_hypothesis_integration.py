import pytest

from app.agent import AgentRuntime
from app.models import LLMResponse, ToolCall
from app.schema_catalog import SchemaCatalog
from app.source_service import SourceService
from app.tools.registration import build_tool_registry


def test_hypothesis_tools_use_simple_model_contract_and_preserve_sql_tool(tmp_path):
    catalog = SchemaCatalog(tmp_path / "catalog.db")
    sources = SourceService(tmp_path / "data", catalog)
    try:
        registry = build_tool_registry(catalog, sources)
        tools = {item["function"]["name"]: item["function"]["parameters"]
                 for item in registry.descriptions()}
        assert "query_data" in tools
        for name in ("compare_groups", "analyze_relationship"):
            assert name in tools
            assert "$ref" not in str(tools[name])
            assert "oneOf" not in str(tools[name])
    finally:
        catalog.close()


@pytest.mark.asyncio
async def test_agent_compares_groups_from_selected_csv(tmp_path, scripted_llm):
    catalog = SchemaCatalog(tmp_path / "catalog.db")
    sources = SourceService(tmp_path / "data", catalog)
    source = sources.register_csv("sales.csv", b"period;amount\nbefore;10\nafter;20\n")
    arguments = {"source_id": source.source_id, "metric_field": "amount",
                 "aggregation": "sum", "group_field": "period",
                 "left_value": "before", "right_value": "after"}
    llm = scripted_llm([
        LLMResponse(tool_calls=[ToolCall(name="compare_groups", arguments=arguments)], finish_reason="tool_calls"),
        LLMResponse(content="Сумма выросла на 10; это наблюдение, не доказательство причины."),
    ])
    try:
        answer = await AgentRuntime(llm, build_tool_registry(catalog, sources), sources=sources).ask(
            "Сравни суммы до и после", [source.source_id])
        assert answer.status == "answered"
        result = answer.tool_results[0]
        assert result.ok, result.error
        assert result.data["results"][0]["status"] == "completed", result.data["results"][0]["error"]
        assert result.data["results"][0]["data"]["delta"] == 10
    finally:
        catalog.close()


def test_relationship_tool_returns_statistical_result_on_csv(tmp_path):
    catalog = SchemaCatalog(tmp_path / "catalog.db")
    sources = SourceService(tmp_path / "data", catalog)
    source = sources.register_csv("sales.csv", b"month;x;y\nJan;1;2\nFeb;2;4\nMar;3;6\nApr;4;8\n")
    try:
        result = build_tool_registry(catalog, sources).execute("analyze_relationship", {
            "source_id": source.source_id, "x_field": "x", "y_field": "y",
            "group_field": "month", "aggregation": "sum",
        })
        assert result.ok, result.error
        check = result.data["results"][0]
        assert check["status"] == "completed", check["error"]
        assert check["data"]["sample_size"] == 4
        assert check["data"]["correlation"] == pytest.approx(1.0)
    finally:
        catalog.close()


def test_average_comparison_reports_sample_sizes_and_uncertainty(tmp_path):
    catalog = SchemaCatalog(tmp_path / "catalog.db")
    sources = SourceService(tmp_path / "data", catalog)
    source = sources.register_csv(
        "sales.csv", b"period;amount\nbefore;9\nbefore;10\nbefore;11\nbefore;10\n"
        b"after;14\nafter;15\nafter;16\nafter;15\n")
    try:
        result = build_tool_registry(catalog, sources).execute("compare_groups", {
            "source_id": source.source_id, "metric_field": "amount", "aggregation": "avg",
            "group_field": "period", "left_value": "before", "right_value": "after",
        })
        assert result.ok, result.error
        check = result.data["results"][0]
        assert check["status"] == "completed", check["error"]
        uncertainty = check["data"]["uncertainty"]
        assert uncertainty["method"] == "welch"
        assert uncertainty["left_count"] == uncertainty["right_count"] == 4
        assert uncertainty["confidence_interval"]["low"] > 0
        assert uncertainty["p_value"] < 0.05
    finally:
        catalog.close()


def test_invalid_hypothesis_field_is_an_error_not_a_successful_check(tmp_path):
    catalog = SchemaCatalog(tmp_path / "catalog.db")
    sources = SourceService(tmp_path / "data", catalog)
    source = sources.register_csv("sales.csv", b"period;amount\nbefore;10\nafter;20\n")
    try:
        result = build_tool_registry(catalog, sources).execute("compare_groups", {
            "source_id": source.source_id, "metric_field": "missing",
            "group_field": "period", "left_value": "before", "right_value": "after",
        })
        assert not result.ok
        assert result.data is None
        assert "field" in result.error.lower()
    finally:
        catalog.close()


def test_comparison_accepts_decimal_comma_values_from_csv(tmp_path):
    catalog = SchemaCatalog(tmp_path / "catalog.db")
    sources = SourceService(tmp_path / "data", catalog)
    source = sources.register_csv(
        "sales.csv", b"period;amount\nbefore;1,5\nbefore;2,5\nafter;3,5\nafter;4,5\n")
    try:
        result = build_tool_registry(catalog, sources).execute("compare_groups", {
            "source_id": source.source_id, "metric_field": "amount", "aggregation": "avg",
            "group_field": "period", "left_value": "before", "right_value": "after",
        })
        assert result.ok, result.error
        check = result.data["results"][0]
        assert check["status"] == "completed", check["error"]
        assert check["data"]["delta"] == pytest.approx(2)
    finally:
        catalog.close()


def test_calendar_lag_works_through_real_csv_query_engine(tmp_path):
    catalog = SchemaCatalog(tmp_path / "catalog.db")
    sources = SourceService(tmp_path / "data", catalog)
    source = sources.register_csv(
        "monthly.csv", b"month;x;y\n2026-01-01;2;0\n2026-02-01;9;2\n"
        b"2026-03-01;1;9\n2026-04-01;7;1\n2026-05-01;3;7\n")
    try:
        result = build_tool_registry(catalog, sources).execute("analyze_relationship", {
            "source_id": source.source_id, "x_field": "x", "y_field": "y",
            "group_field": "month", "time_grain": "month", "max_lag": 1,
        })
        assert result.ok, result.error
        check = result.data["results"][0]
        assert check["status"] == "completed", check["error"]
        assert check["data"]["lag_results"][1]["sample_size"] == 4
        assert check["data"]["lag_results"][1]["correlation"] == pytest.approx(1)
    finally:
        catalog.close()

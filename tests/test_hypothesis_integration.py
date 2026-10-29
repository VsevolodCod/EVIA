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

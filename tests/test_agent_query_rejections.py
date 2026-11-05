"""Rejected chart calls allow recovery and report the real error early."""

import pytest

from app.agent import AgentRuntime
from app.models import LLMResponse, ToolCall
from app.schema_catalog import SchemaCatalog
from app.source_service import SourceService
from app.tools import build_tool_registry


def chart_call(source_id: str, *, invalid: bool = False) -> LLMResponse:
    return LLMResponse(
        tool_calls=[ToolCall(name="build_chart", arguments={"definition": {
            "type": "table", "title": "Filtered rows",
            "fields": [{"source_id": source_id, "field": "revenue"}],
            "filters": [{"field": {"source_id": source_id, "field": "revenue"},
                         "operator": "execute_sql" if invalid else "lt", "value": 0}],
        }})],
        finish_reason="tool_calls",
    )


@pytest.mark.asyncio
async def test_repeated_rejected_chart_calls_report_query_error_early(tmp_path, scripted_llm):
    catalog = SchemaCatalog(tmp_path / "catalog.db")
    sources = SourceService(tmp_path / "data", catalog)
    source = sources.register_csv("events.csv", b"period,revenue\n2026-01-02,100\n")
    model = scripted_llm([chart_call(source.source_id, invalid=True) for _ in range(5)])
    try:
        answer = await AgentRuntime(
            model, build_tool_registry(catalog, sources), max_steps=5, sources=sources
        ).ask("Покажи строки с отрицательной выручкой", [source.source_id])
        assert answer.status == "error"
        assert answer.error and answer.error.code == "QUERY_REJECTED"
        assert "запрос" in answer.answer.lower() and "лимит шагов" not in answer.answer.lower()
        assert answer.steps == 2
        assert len(answer.tool_results) == 2
        assert all(result.error == "INVALID_TOOL_ARGUMENTS" for result in answer.tool_results)
        assert len(model.responses) == 3
    finally:
        catalog.close()


@pytest.mark.asyncio
async def test_one_rejection_can_recover_to_a_valid_empty_result(tmp_path, scripted_llm):
    catalog = SchemaCatalog(tmp_path / "catalog.db")
    sources = SourceService(tmp_path / "data", catalog)
    source = sources.register_csv("events.csv", b"period,revenue\n2026-01-02,100\n")
    model = scripted_llm([
        chart_call(source.source_id, invalid=True),
        chart_call(source.source_id),
        LLMResponse(content="По заданному условию строк нет."),
    ])
    try:
        answer = await AgentRuntime(
            model, build_tool_registry(catalog, sources), max_steps=5, sources=sources
        ).ask("Покажи строки с отрицательной выручкой", [source.source_id])
        assert answer.status == "answered"
        assert [result.ok for result in answer.tool_results] == [False, True]
        built = answer.tool_results[1].data
        assert built['success'] and built['result']['rows'] == []
        assert "строк нет" in answer.answer
    finally:
        catalog.close()


@pytest.mark.asyncio
async def test_successful_chart_resets_the_rejection_counter(tmp_path, scripted_llm):
    catalog = SchemaCatalog(tmp_path / "catalog.db")
    sources = SourceService(tmp_path / "data", catalog)
    source = sources.register_csv("events.csv", b"revenue\n100\n")
    model = scripted_llm([
        chart_call(source.source_id, invalid=True),
        chart_call(source.source_id),
        chart_call(source.source_id, invalid=True),
        chart_call(source.source_id),
        LLMResponse(content="По заданному условию строк нет."),
    ])
    try:
        answer = await AgentRuntime(
            model, build_tool_registry(catalog, sources), max_steps=5, sources=sources,
        ).ask("Покажи строки с отрицательной выручкой", [source.source_id])
        assert answer.status == "answered"
        assert answer.steps == 5
        assert [result.ok for result in answer.tool_results] == [False, True, False, True]
        assert not model.responses
    finally:
        catalog.close()

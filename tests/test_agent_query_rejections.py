"""Repeated invalid SQL should not exhaust the agent with an unrelated error."""

import pytest

from app.agent import AgentRuntime
from app.models import LLMResponse, ToolCall
from app.schema_catalog import SchemaCatalog
from app.source_service import SourceService
from app.tools import build_tool_registry


def query_call(source_id: str, sql: str) -> LLMResponse:
    return LLMResponse(
        tool_calls=[ToolCall(name="query_data", arguments={"source_id": source_id, "sql": sql})],
        finish_reason="tool_calls",
    )


@pytest.mark.asyncio
async def test_repeated_rejected_sql_reports_query_error_early(tmp_path, scripted_llm):
    catalog = SchemaCatalog(tmp_path / "catalog.db")
    sources = SourceService(tmp_path / "data", catalog)
    source = sources.register_csv("events.csv", b"period,revenue\n2026-01-02,100\n")
    model = scripted_llm([query_call(source.source_id, "DELETE FROM source") for _ in range(5)])
    try:
        answer = await AgentRuntime(
            model, build_tool_registry(catalog, sources), max_steps=5, sources=sources
        ).ask("Покажи строки за 2025 год", [source.source_id])
        assert answer.status == "error"
        assert answer.error and answer.error.code == "QUERY_REJECTED"
        assert "запрос" in answer.answer.lower() and "лимит шагов" not in answer.answer.lower()
        assert answer.steps == 2
        assert len(answer.tool_results) == 2
        assert all(result.error == "QUERY_REJECTED" for result in answer.tool_results)
        assert len(model.responses) == 3
    finally:
        catalog.close()


@pytest.mark.asyncio
async def test_one_rejection_can_recover_to_a_valid_empty_result(tmp_path, scripted_llm):
    catalog = SchemaCatalog(tmp_path / "catalog.db")
    sources = SourceService(tmp_path / "data", catalog)
    source = sources.register_csv("events.csv", b"period,revenue\n2026-01-02,100\n")
    model = scripted_llm([
        query_call(source.source_id, "DELETE FROM source"),
        query_call(source.source_id, "SELECT * FROM source WHERE 1 = 0"),
        LLMResponse(content="По заданному условию строк нет."),
    ])
    try:
        answer = await AgentRuntime(
            model, build_tool_registry(catalog, sources), max_steps=5, sources=sources
        ).ask("Покажи строки за 2025 год", [source.source_id])
        assert answer.status == "answered"
        assert [result.ok for result in answer.tool_results] == [False, True]
        assert answer.results and answer.results[0].rows == []
        assert "строк нет" in answer.answer
    finally:
        catalog.close()

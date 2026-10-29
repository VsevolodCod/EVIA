"""Distinct outcomes must come from evidence, without asking the model to guess."""

import pytest

from app.agent import AgentRuntime
from app.models import LLMResponse, ToolCall
from app.schema_catalog import SchemaCatalog
from app.source_service import SourceService
from app.tools import build_tool_registry


class NoModel:
    async def chat(self, *_args, **_kwargs):
        raise AssertionError("model must not be called")


@pytest.fixture
def source_agent(tmp_path):
    catalog = SchemaCatalog(tmp_path / "catalog.db")
    sources = SourceService(tmp_path / "data", catalog)
    source = sources.register_csv(
        "events.csv", b"period,revenue\n2026-01-02,100\n2025-03-05,200\n"
    )
    try:
        yield source, sources, build_tool_registry(catalog, sources)
    finally:
        catalog.close()


@pytest.mark.asyncio
async def test_off_topic_request_is_unsupported_without_tools_or_model(source_agent):
    source, sources, tools = source_agent
    answer = await AgentRuntime(NoModel(), tools, sources=sources).ask(
        "Напиши стихотворение", [source.source_id]
    )
    assert answer.status == "clarification"
    assert answer.outcome == "unsupported"
    assert answer.steps == 0
    assert answer.tool_results == []
    assert answer.results == []


@pytest.mark.asyncio
async def test_simple_year_filter_returns_actual_empty_and_nonempty_rows(source_agent):
    source, sources, tools = source_agent
    agent = AgentRuntime(NoModel(), tools, sources=sources)

    empty = await agent.ask("Покажи строки за 2024 год", [source.source_id])
    assert empty.status == "answered"
    assert empty.outcome == "answer"
    assert empty.results and empty.results[0].rows == []
    assert "совпадений нет" in empty.answer.lower()
    assert empty.steps == 0

    found = await agent.ask("Покажи строки за 2025 год", [source.source_id])
    assert found.status == "answered"
    assert found.results and found.results[0].returned_rows == 1
    assert found.results[0].rows[0][1] == "200"
    assert "совпадений нет" not in found.answer.lower()


@pytest.mark.asyncio
async def test_empty_query_result_ends_tool_loop_before_chart(source_agent):
    source, sources, tools = source_agent

    class Model:
        calls = 0

        async def chat(self, *_args, **_kwargs):
            self.calls += 1
            if self.calls > 1:
                raise AssertionError("empty result must stop before a chart attempt")
            return LLMResponse(
                tool_calls=[ToolCall(name="query_data", arguments={
                    "source_id": source.source_id,
                    "sql": "SELECT * FROM source WHERE 1 = 0",
                })],
                finish_reason="tool_calls",
            )

    model = Model()
    answer = await AgentRuntime(model, tools, sources=sources).ask(
        "Покажи события с несуществующим значением", [source.source_id]
    )
    assert answer.status == "answered"
    assert answer.results and answer.results[0].rows == []
    assert "совпадений нет" in answer.answer.lower()
    assert model.calls == 1

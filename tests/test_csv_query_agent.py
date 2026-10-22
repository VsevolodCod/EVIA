import json

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.agent import AgentRuntime
from app.models import LLMResponse
from app.models import ChatMessage
from app.schema_catalog import SchemaCatalog
from app.source_service import SourceService
from app.tools import build_tool_registry


class ScriptedProvider:
    def __init__(self, *plans):
        self.plans = list(plans)
        self.messages = []

    async def chat(self, messages, tools=None):
        self.messages.append((messages, tools))
        return LLMResponse(content=json.dumps(self.plans.pop(0), ensure_ascii=False))


def agent_with_csv(tmp_path, provider):
    catalog = SchemaCatalog(tmp_path / "catalog.db")
    sources = SourceService(tmp_path / "data", catalog)
    source = sources.register_csv(
        "sales.csv", b"month,revenue\n2026-01,120\n2026-02,180\n"
    )
    agent = AgentRuntime(provider, build_tool_registry(catalog, sources), sources=sources)
    return agent, source, catalog


@pytest.mark.asyncio
async def test_selected_csv_question_executes_model_sql_and_returns_typed_result(tmp_path):
    provider = ScriptedProvider({
        "intent": "sum_revenue",
        "sql": 'SELECT SUM(TRY_CAST("revenue" AS BIGINT)) AS "total" FROM source',
        "explanation": "Выручка по всем месяцам",
    })
    agent, source, catalog = agent_with_csv(tmp_path, provider)
    try:
        answer = await agent.ask("Сколько всего выручки?", [source.source_id])
        assert answer.status == "answered"
        assert answer.answer_kind == "computed"
        assert answer.request_id
        assert answer.analysis.sql == (
            'SELECT SUM(CAST(NULLIF(REPLACE(TRIM("revenue"), \',\', \'.\'), \'\') AS BIGINT)) AS "total" FROM source'
        )
        assert answer.results[0].rows == [[300]]
        assert answer.results[0].columns[0].data_type == "integer"
        assert answer.tool_results[0].tool_name == "query_data"
        assert "300" in answer.answer
        assert provider.messages[0][1] is None
        assert "revenue" in provider.messages[0][0][0].content
        assert answer.timing.llm_ms >= 0
        assert answer.timing.tools_ms >= 0
    finally:
        catalog.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("aggregate,expected", [("SUM", 301.0), ("AVG", 150.5)])
async def test_decimal_comma_and_dot_are_both_counted_without_changing_raw_csv(tmp_path, aggregate, expected):
    catalog = SchemaCatalog(tmp_path / "catalog.db")
    sources = SourceService(tmp_path / "data", catalog)
    source = sources.register_csv("sales.csv", b"id;revenue\n001;120,5\n002;180.5\n003;\n")
    provider = ScriptedProvider({
        "intent": aggregate.lower(),
        "sql": f'SELECT {aggregate}(TRY_CAST("revenue" AS DOUBLE)) AS total FROM source',
        "explanation": "",
    })
    agent = AgentRuntime(provider, build_tool_registry(catalog, sources), sources=sources)
    try:
        answer = await agent.ask("Какая выручка?", [source.source_id])
        assert answer.status == "answered"
        assert answer.results[0].rows[0][0] == pytest.approx(expected)
        assert sources.preview(source.source_id, limit=1)[0] == {"id": "001", "revenue": "120,5"}
    finally:
        catalog.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("aggregate", ["SUM", "AVG"])
async def test_invalid_numeric_value_beyond_schema_sample_cannot_be_silently_skipped(tmp_path, aggregate):
    catalog = SchemaCatalog(tmp_path / "catalog.db")
    sources = SourceService(tmp_path / "data", catalog)
    content = "id;revenue\n" + "".join(f"{index:04d};1,5\n" for index in range(500)) + "0500;broken\n"
    source = sources.register_csv("sales.csv", content.encode())
    plan = {"intent": aggregate.lower(), "sql": f'SELECT {aggregate}(TRY_CAST("revenue" AS DOUBLE)) AS total FROM source', "explanation": ""}
    provider = ScriptedProvider(plan, plan)
    agent = AgentRuntime(provider, build_tool_registry(catalog, sources), sources=sources)
    try:
        answer = await agent.ask("Сумма выручки?", [source.source_id])
        assert answer.status == "error"
        assert answer.results == []
        assert [item.ok for item in answer.tool_results] == [False, False]
    finally:
        catalog.close()


@pytest.mark.asyncio
async def test_wrapped_numeric_try_cast_cannot_hide_invalid_values(tmp_path):
    catalog = SchemaCatalog(tmp_path / "catalog.db")
    sources = SourceService(tmp_path / "data", catalog)
    content = "id;revenue\n" + "001;1,5\n" * 500 + "501;broken\n"
    source = sources.register_csv("sales.csv", content.encode())
    plan = {"intent": "sum", "sql": 'SELECT SUM(TRY_CAST(TRIM("revenue") AS DOUBLE)) AS total FROM source', "explanation": ""}
    provider = ScriptedProvider(plan, plan)
    agent = AgentRuntime(provider, build_tool_registry(catalog, sources), sources=sources)
    try:
        answer = await agent.ask("Сумма выручки?", [source.source_id])
        assert answer.status == "error"
        assert answer.results == []
        assert [item.ok for item in answer.tool_results] == [False, False]
    finally:
        catalog.close()


@pytest.mark.asyncio
async def test_numeric_normalization_does_not_drop_a_second_sql_statement(tmp_path):
    plan = {
        "intent": "sum", "sql": 'SELECT SUM(TRY_CAST("revenue" AS DOUBLE)) FROM source; DROP TABLE source',
        "explanation": "",
    }
    provider = ScriptedProvider(plan, plan)
    agent, source, catalog = agent_with_csv(tmp_path, provider)
    try:
        answer = await agent.ask("Сумма выручки?", [source.source_id])
        assert answer.status == "error"
        assert answer.results == []
    finally:
        catalog.close()


@pytest.mark.asyncio
async def test_rejected_sql_is_repaired_once_with_visible_trace(tmp_path):
    provider = ScriptedProvider(
        {"intent": "count", "sql": "SELECT COUNT(*) FROM invented", "explanation": ""},
        {"intent": "count", "sql": 'SELECT COUNT(*) AS "count" FROM source', "explanation": ""},
    )
    agent, source, catalog = agent_with_csv(tmp_path, provider)
    try:
        answer = await agent.ask("Сколько строк?", [source.source_id])
        assert [tool.ok for tool in answer.tool_results] == [False, True]
        assert answer.results[0].rows == [[2]]
        assert answer.steps == 2
        assert len(provider.messages) == 2
    finally:
        catalog.close()


@pytest.mark.asyncio
async def test_empty_result_does_not_invent_a_number(tmp_path):
    provider = ScriptedProvider({
        "intent": "filter", "sql": "SELECT revenue FROM source WHERE month = '2099-01'", "explanation": "",
    })
    agent, source, catalog = agent_with_csv(tmp_path, provider)
    try:
        answer = await agent.ask("Выручка в 2099 году?", [source.source_id])
        assert answer.results[0].rows == []
        assert "нет строк" in answer.answer.lower()
        assert "2099" not in answer.answer
    finally:
        catalog.close()


@pytest.mark.asyncio
async def test_invalid_model_plan_never_runs_sql(tmp_path):
    provider = ScriptedProvider(
        {"intent": "count", "sql": "SELECT 1"},
        {"intent": "count", "sql": "SELECT 1"},
    )
    agent, source, catalog = agent_with_csv(tmp_path, provider)
    try:
        answer = await agent.ask("Сколько строк?", [source.source_id])
        assert answer.status == "error"
        assert answer.results == []
        assert answer.tool_results == []
    finally:
        catalog.close()


@pytest.mark.asyncio
async def test_constant_query_is_rejected_even_when_executor_would_accept_it(tmp_path):
    provider = ScriptedProvider(
        {"intent": "count", "sql": "SELECT 999 AS count", "explanation": ""},
        {"intent": "count", "sql": 'SELECT COUNT(*) AS "count" FROM source', "explanation": ""},
    )
    agent, source, catalog = agent_with_csv(tmp_path, provider)
    try:
        answer = await agent.ask("Сколько строк?", [source.source_id])
        assert answer.results[0].rows == [[2]]
        assert [tool.ok for tool in answer.tool_results] == [False, True]
    finally:
        catalog.close()


@pytest.mark.asyncio
async def test_constant_projection_from_source_cannot_claim_computed_csv_result(tmp_path):
    provider = ScriptedProvider(
        {"intent": "sum", "sql": "SELECT 999 AS total FROM source LIMIT 1", "explanation": ""},
        {"intent": "sum", "sql": 'SELECT SUM(TRY_CAST("revenue" AS DOUBLE)) AS total FROM source', "explanation": ""},
    )
    agent, source, catalog = agent_with_csv(tmp_path, provider)
    try:
        answer = await agent.ask("Сколько всего выручки?", [source.source_id])
        assert answer.status == "answered"
        assert [tool.ok for tool in answer.tool_results] == [False, True]
        assert answer.results[0].rows == [[300.0]]
    finally:
        catalog.close()


@pytest.mark.asyncio
async def test_http_csv_question_returns_sql_and_computed_table(tmp_path, monkeypatch):
    from app import main as module

    provider = ScriptedProvider({
        "intent": "sum_revenue",
        "sql": 'SELECT SUM(TRY_CAST("revenue" AS BIGINT)) AS "total" FROM source',
        "explanation": "",
    })
    catalog = SchemaCatalog(tmp_path / "catalog.db")
    sources = SourceService(tmp_path / "data", catalog)
    agent = AgentRuntime(provider, build_tool_registry(catalog, sources), sources=sources)
    monkeypatch.setattr(module, "catalog", catalog)
    monkeypatch.setattr(module, "source_service", sources)
    monkeypatch.setattr(module, "agent", agent)
    monkeypatch.setattr(module.settings, "chat_db_path", tmp_path / "chat.db")
    async with module.app.router.lifespan_context(module.app):
        async with AsyncClient(transport=ASGITransport(app=module.app), base_url="http://test") as client:
            upload = await client.post("/sources/csv", files={
                "file": ("sales.csv", b"month,revenue\n2026-01,120\n2026-02,180\n", "text/csv")
            })
            assert upload.status_code == 200
            source_id = upload.json()["source_id"]
            chat = await client.post("/agent/chat", json={
                "question": "Сколько всего выручки?", "source_ids": [source_id],
            })
            assert chat.status_code == 200
            data = chat.json()
            assert data["status"] == "answered"
            assert data["analysis"]["sql"].startswith("SELECT SUM")
            assert data["results"][0]["rows"] == [[300]]
            assert data["tool_results"][0]["data"]["rows"] == [[300]]
            assert data["request_id"]
            assert data["chat_id"]


@pytest.mark.asyncio
async def test_followup_context_is_available_without_becoming_sql_or_data(tmp_path):
    provider = ScriptedProvider({
        "intent": "count", "sql": 'SELECT COUNT(*) AS "count" FROM source', "explanation": "",
    })
    agent, source, catalog = agent_with_csv(tmp_path, provider)
    try:
        await agent.ask("А сколько строк?", [source.source_id], history=[
            ChatMessage(role="user", content="Сначала посмотрим выручку"),
            ChatMessage(role="assistant", content="total: 300"),
        ])
        messages = provider.messages[0][0]
        assert [message.role for message in messages] == ["system", "user", "assistant", "user"]
        assert messages[-1].content == "А сколько строк?"
    finally:
        catalog.close()


@pytest.mark.asyncio
async def test_out_of_schema_question_returns_clarification_without_query(tmp_path):
    provider = ScriptedProvider({"intent": "clarification", "sql": None, "explanation": ""})
    agent, source, catalog = agent_with_csv(tmp_path, provider)
    try:
        answer = await agent.ask("Какая погода?", [source.source_id])
        assert answer.status == "clarification"
        assert answer.results == []
        assert answer.tool_results == []
    finally:
        catalog.close()


@pytest.mark.asyncio
async def test_general_dataset_question_gets_count_and_period_even_if_model_asks_to_clarify(tmp_path):
    catalog = SchemaCatalog(tmp_path / "catalog.db")
    sources = SourceService(tmp_path / "data", catalog)
    source = sources.register_csv(
        "support.csv",
        b"created_at,ticket\n2024-10-01T09:00:00,A\n2024-10-03T10:30:00,B\n",
    )
    provider = ScriptedProvider({"intent": "clarification", "sql": None, "explanation": ""})
    agent = AgentRuntime(provider, build_tool_registry(catalog, sources), sources=sources)
    try:
        answer = await agent.ask("Что есть в этих данных? За какой период они и сколько их?", [source.source_id])
        assert answer.status == "answered"
        assert answer.answer_kind == "computed"
        assert "2 строки" in answer.answer
        assert "01.10.2024" in answer.answer
        assert "03.10.2024" in answer.answer
        assert answer.results[0].rows[0][0] == 2
        assert answer.tool_results[0].ok
    finally:
        catalog.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [httpx.ConnectError("offline"), httpx.ReadTimeout("timeout")])
async def test_unavailable_local_model_returns_request_id_and_timing(tmp_path, failure, caplog):
    class UnavailableProvider:
        async def chat(self, messages, tools=None):
            raise failure

    agent, source, catalog = agent_with_csv(tmp_path, UnavailableProvider())
    try:
        answer = await agent.ask("Сколько строк?", [source.source_id])
        assert answer.status == "error"
        assert answer.error.code == "MODEL_UNAVAILABLE"
        assert answer.error.request_id == answer.request_id
        assert len(answer.timing.calls) == 1
        assert answer.results == []
        assert "outcome=error" in caplog.text
    finally:
        catalog.close()


@pytest.mark.asyncio
async def test_missing_selected_source_is_not_sent_to_model(tmp_path):
    provider = ScriptedProvider()
    agent, _, catalog = agent_with_csv(tmp_path, provider)
    try:
        answer = await agent.ask("Сколько строк?", ["missing"])
        assert answer.status == "error"
        assert answer.error.code == "SOURCE_NOT_FOUND"
        assert provider.messages == []
    finally:
        catalog.close()


@pytest.mark.asyncio
async def test_malformed_json_never_reaches_sql_executor(tmp_path):
    class BrokenProvider:
        calls = 0

        async def chat(self, messages, tools=None):
            self.calls += 1
            return LLMResponse(content="```json\nnot a plan\n```")

    provider = BrokenProvider()
    agent, source, catalog = agent_with_csv(tmp_path, provider)
    try:
        answer = await agent.ask("Сколько строк?", [source.source_id])
        assert answer.status == "error"
        assert answer.error.code == "VALIDATION_ERROR"
        assert answer.tool_results == []
        assert provider.calls == 2
    finally:
        catalog.close()


@pytest.mark.asyncio
async def test_truncated_json_plan_cannot_execute_sql_even_if_syntactically_valid(tmp_path):
    class TruncatedProvider:
        calls = 0

        async def chat(self, messages, tools=None):
            self.calls += 1
            return LLMResponse(
                content=json.dumps({"intent": "count", "sql": "SELECT COUNT(*) FROM source", "explanation": ""}),
                finish_reason="length",
            )

    provider = TruncatedProvider()
    agent, source, catalog = agent_with_csv(tmp_path, provider)
    try:
        answer = await agent.ask("Сколько строк?", [source.source_id])
        assert answer.status == "error"
        assert answer.error and answer.error.code == "MODEL_OUTPUT_INCOMPLETE"
        assert answer.results == []
        assert answer.tool_results == []
        assert provider.calls == 2
    finally:
        catalog.close()


@pytest.mark.asyncio
async def test_invented_column_is_repaired_against_current_schema(tmp_path):
    provider = ScriptedProvider(
        {"intent": "sum", "sql": 'SELECT SUM(TRY_CAST("fantasy" AS DOUBLE)) AS total FROM source', "explanation": ""},
        {"intent": "sum", "sql": 'SELECT SUM(TRY_CAST("revenue" AS DOUBLE)) AS total FROM source', "explanation": ""},
    )
    agent, source, catalog = agent_with_csv(tmp_path, provider)
    try:
        answer = await agent.ask("Сколько всего выручки?", [source.source_id])
        assert [tool.ok for tool in answer.tool_results] == [False, True]
        assert answer.results[0].rows == [[300.0]]
    finally:
        catalog.close()


@pytest.mark.asyncio
async def test_average_datetime_rejects_numeric_cast_and_uses_timestamp(tmp_path):
    provider = ScriptedProvider(
        {"intent": "average", "sql": 'SELECT AVG(TRY_CAST("Первый ответ (МСК)" AS DOUBLE)) AS avg_first_answer FROM source', "explanation": ""},
        {"intent": "average", "sql": 'SELECT AVG(TRY_CAST("Первый ответ (МСК)" AS TIMESTAMP)) AS avg_first_answer FROM source', "explanation": ""},
    )
    catalog = SchemaCatalog(tmp_path / "catalog.db")
    sources = SourceService(tmp_path / "data", catalog)
    source = sources.register_csv(
        "support.csv", 'Первый ответ (МСК)\n2024-10-01 01:00:00\n2024-10-01 03:00:00\n'.encode(),
    )
    agent = AgentRuntime(provider, build_tool_registry(catalog, sources), sources=sources)
    try:
        answer = await agent.ask("Какое среднее значение в столбце первый ответ?", [source.source_id])
        assert "datetime" in provider.messages[0][0][0].content
        assert [tool.ok for tool in answer.tool_results] == [False, True]
        assert answer.results[0].rows == [["2024-10-01T02:00:00"]]
        assert "Средняя дата/время: 01.10.2024 02:00:00" in answer.answer
        assert "avg_first_answer" not in answer.answer
    finally:
        catalog.close()

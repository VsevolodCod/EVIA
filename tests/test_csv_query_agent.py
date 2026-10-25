import json

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.agent import AgentRuntime
from app.csv_query_agent import _question_route
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
@pytest.mark.parametrize("question", [
    "Какие есть столбцы?",
    "Перечисли поля в CSV",
    "Какова структура таблицы?",
    "Назови колонки этого источника",
    "Какие поля содержатся в таблице?",
])
async def test_schema_questions_use_current_header_without_model_or_rows(tmp_path, question):
    catalog = SchemaCatalog(tmp_path / "catalog.db")
    sources = SourceService(tmp_path / "data", catalog)
    source = sources.register_csv("empty.csv", "Номер,Дата ответа\n".encode())
    provider = ScriptedProvider()
    agent = AgentRuntime(provider, build_tool_registry(catalog, sources), sources=sources)
    try:
        answer = await agent.ask(question, [source.source_id])
        assert answer.status == "answered"
        assert answer.answer_kind == "computed"
        assert "Номер" in answer.answer
        assert "Дата ответа" in answer.answer
        assert "нет строк" not in answer.answer.lower()
        assert answer.steps == 0
        assert answer.timing.calls == []
        assert provider.messages == []
        assert answer.tool_results[0].tool_name == "get_schema"
    finally:
        catalog.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("question", [
    "Что передо мной?",
    "Что есть в этих данных?",
    "Что ещё можешь скзаать про эти данные?",
    "Что еще можешь сказать про эти данные?",
    "За какой период они и сколько их?",
])
async def test_overview_questions_use_verified_count_period_and_fields_without_model(tmp_path, question):
    catalog = SchemaCatalog(tmp_path / "catalog.db")
    sources = SourceService(tmp_path / "data", catalog)
    source = sources.register_csv(
        "tickets.csv",
        b"created_at,ticket\n2024-10-01T09:00:00,A\n2024-10-03T10:30:00,B\n",
    )
    provider = ScriptedProvider()
    agent = AgentRuntime(provider, build_tool_registry(catalog, sources), sources=sources)
    try:
        answer = await agent.ask(question, [source.source_id])
        assert answer.status == "answered"
        assert answer.answer_kind == "computed"
        assert "2 строки" in answer.answer
        assert "created_at" in answer.answer
        assert "ticket" in answer.answer
        assert "01.10.2024" in answer.answer
        assert "03.10.2024" in answer.answer
        assert answer.steps == 0
        assert provider.messages == []
    finally:
        catalog.close()


@pytest.mark.asyncio
async def test_overview_uses_profile_facts_without_inventing_business_meaning(tmp_path):
    catalog = SchemaCatalog(tmp_path / "catalog.db")
    sources = SourceService(tmp_path / "data", catalog)
    source = sources.register_csv(
        "anonymous.csv",
        b"event_date,mystery_value,segment\n2024-10-01,10,A\n2024-10-03,,B\n",
    )
    agent = AgentRuntime(ScriptedProvider(), build_tool_registry(catalog, sources), sources=sources)
    try:
        answer = await agent.ask("Что есть в этих данных?", [source.source_id])
        assert answer.status == "answered"
        assert "2 строки" in answer.answer
        assert "event_date: 01.10.2024 — 03.10.2024" in answer.answer
        assert "mystery_value: 1 пустая строка" in answer.answer
        assert "mystery_value" in answer.answer
        assert "выруч" not in answer.answer.casefold()
        assert "Можно спросить" in answer.answer
        profile_trace = next(tool for tool in answer.tool_results if tool.tool_name == "get_profile")
        assert profile_trace.data["snapshot_id"] == source.snapshot_id
    finally:
        catalog.close()


@pytest.mark.asyncio
async def test_schema_route_does_not_steal_a_calculation_about_one_column(tmp_path):
    provider = ScriptedProvider({
        "intent": "average_revenue",
        "sql": 'SELECT AVG(TRY_CAST("revenue" AS DOUBLE)) AS average FROM source',
        "explanation": "",
    })
    agent, source, catalog = agent_with_csv(tmp_path, provider)
    try:
        answer = await agent.ask("Покажи среднее значение в столбце revenue", [source.source_id])
        assert answer.results[0].rows == [[150.0]]
        assert len(provider.messages) == 1
    finally:
        catalog.close()


@pytest.mark.parametrize("question", [
    "Какие поля содержат пропуски?",
    "Покажи значения в столбце revenue",
    "Какие колонки имеют дубликаты?",
    "Опиши распределение данных по категориям",
    "Расскажи про среднюю выручку в данных",
    "Что здесь с продажами по регионам?",
    "Покажи колонки с пустыми строками",
    "А за какой период заявки со статусом закрыто и сколько их?",
    "А за какой период данные по closed_at и сколько их?",
    "Покажи данные из столбцов",
])
def test_schema_route_keeps_analysis_questions_for_the_sql_path(question):
    assert _question_route(question) is None


@pytest.mark.asyncio
async def test_schema_answer_retries_if_source_is_reimported_between_schema_and_source_reads(tmp_path, monkeypatch):
    catalog = SchemaCatalog(tmp_path / "catalog.db")
    sources = SourceService(tmp_path / "data", catalog)
    source = sources.register_csv("before.csv", b"old_field\n1\n")
    original_get_schema = sources.get_schema
    changed = False

    def get_schema_during_reimport(source_id):
        nonlocal changed
        schema = original_get_schema(source_id)
        if not changed:
            changed = True
            sources.register_csv("after.csv", b"new_field\n2\n", source_id=source_id)
        return schema

    monkeypatch.setattr(sources, "get_schema", get_schema_during_reimport)
    provider = ScriptedProvider()
    agent = AgentRuntime(provider, build_tool_registry(catalog, sources), sources=sources)
    try:
        answer = await agent.ask("Какие есть столбцы?", [source.source_id])
        latest = catalog.get_source(source.source_id)
        assert answer.status == "answered"
        assert "new_field" in answer.answer
        assert "old_field" not in answer.answer
        assert answer.tool_results[0].data["snapshot_id"] == latest.snapshot_id
        assert answer.tool_results[0].data["schema_version"] == latest.schema_version
        assert provider.messages == []
    finally:
        catalog.close()


@pytest.mark.asyncio
async def test_overview_never_combines_old_schema_with_new_snapshot_query(tmp_path, monkeypatch):
    catalog = SchemaCatalog(tmp_path / "catalog.db")
    sources = SourceService(tmp_path / "data", catalog)
    source = sources.register_csv("before.csv", b"created_at,old_field\n2024-01-01,1\n")
    original_query = sources.query
    changed = False

    def query_during_reimport(source_id, sql, **kwargs):
        nonlocal changed
        if not changed:
            changed = True
            sources.register_csv("after.csv", b"created_at,new_field\n2026-02-01,2\n", source_id=source_id)
        return original_query(source_id, sql, **kwargs)

    monkeypatch.setattr(sources, "query", query_during_reimport)
    agent = AgentRuntime(ScriptedProvider(), build_tool_registry(catalog, sources), sources=sources)
    try:
        answer = await agent.ask("Что есть в этих данных?", [source.source_id])
        latest = catalog.get_source(source.source_id)
        assert answer.status == "answered"
        assert "new_field" in answer.answer
        assert "old_field" not in answer.answer
        assert answer.results[0].provenance[0].snapshot_id == latest.snapshot_id
        assert answer.tool_results[0].data["schema_version"] == latest.schema_version
    finally:
        catalog.close()


@pytest.mark.asyncio
async def test_overview_retries_if_reimport_replaces_queried_date_column(tmp_path, monkeypatch):
    catalog = SchemaCatalog(tmp_path / "catalog.db")
    sources = SourceService(tmp_path / "data", catalog)
    source = sources.register_csv("before.csv", b"created_at,old_field\n2024-01-01,1\n")
    original_query = sources.query
    changed = False

    def query_during_reimport(source_id, sql, **kwargs):
        nonlocal changed
        if not changed:
            changed = True
            sources.register_csv("after.csv", b"closed_at,new_field\n2026-02-01,2\n", source_id=source_id)
        return original_query(source_id, sql, **kwargs)

    monkeypatch.setattr(sources, "query", query_during_reimport)
    agent = AgentRuntime(ScriptedProvider(), build_tool_registry(catalog, sources), sources=sources)
    try:
        answer = await agent.ask("Что есть в этих данных?", [source.source_id])
        assert answer.status == "answered"
        assert "closed_at" in answer.answer
        assert "created_at" not in answer.answer
        assert "01.02.2026" in answer.answer
        assert answer.results[0].provenance[0].snapshot_id == catalog.get_source(source.source_id).snapshot_id
    finally:
        catalog.close()


@pytest.mark.asyncio
async def test_overview_retries_if_schema_version_changes_for_same_snapshot(tmp_path, monkeypatch):
    catalog = SchemaCatalog(tmp_path / "catalog.db")
    sources = SourceService(tmp_path / "data", catalog)
    source = sources.register_csv("events.csv", b"created_at,value\n2024-01-01,1\n")
    original_query = sources.query
    changed = False

    def query_during_schema_refresh(source_id, sql, **kwargs):
        nonlocal changed
        if not changed:
            changed = True
            refreshed_source = catalog.get_source(source_id)
            refreshed_schema = catalog.get_schema(source_id)
            refreshed_source.schema_version += 1
            refreshed_schema.version += 1
            catalog.save_schema(refreshed_schema)
            catalog.upsert_source(refreshed_source)
        return original_query(source_id, sql, **kwargs)

    monkeypatch.setattr(sources, "query", query_during_schema_refresh)
    agent = AgentRuntime(ScriptedProvider(), build_tool_registry(catalog, sources), sources=sources)
    try:
        answer = await agent.ask("Что есть в этих данных?", [source.source_id])
        assert answer.status == "answered"
        assert answer.tool_results[0].data["schema_version"] == 2
        assert answer.results[0].provenance[0].schema_version == 2
    finally:
        catalog.close()


@pytest.mark.asyncio
async def test_overview_counts_legacy_schema_without_saved_row_count(tmp_path):
    catalog = SchemaCatalog(tmp_path / "catalog.db")
    sources = SourceService(tmp_path / "data", catalog)
    source = sources.register_csv("legacy.csv", b"region,amount\nA,10\nB,20\n")
    schema = sources.get_schema(source.source_id)
    schema.objects[0].row_count = None
    catalog.save_schema(schema)
    provider = ScriptedProvider()
    agent = AgentRuntime(provider, build_tool_registry(catalog, sources), sources=sources)
    try:
        answer = await agent.ask("Что есть в этих данных?", [source.source_id])
        assert answer.status == "answered"
        assert "2 строки" in answer.answer
        assert answer.tool_results[-1].tool_name == "query_data"
        assert provider.messages == []
    finally:
        catalog.close()


@pytest.mark.asyncio
async def test_schema_followup_uses_new_selected_source_after_chat_history(tmp_path):
    catalog = SchemaCatalog(tmp_path / "catalog.db")
    sources = SourceService(tmp_path / "data", catalog)
    first = sources.register_csv("first.csv", b"old_name\n1\n")
    second = sources.register_csv("second.csv", b"renamed_field\n2\n")
    provider = ScriptedProvider()
    agent = AgentRuntime(provider, build_tool_registry(catalog, sources), sources=sources)
    try:
        history = [ChatMessage(role="user", content="Какие поля у первого источника?"),
                   ChatMessage(role="assistant", content="old_name")]
        answer = await agent.ask("А какие поля здесь?", [second.source_id], history=history)
        assert answer.status == "answered"
        assert "renamed_field" in answer.answer
        assert "old_name" not in answer.answer
        assert provider.messages == []
    finally:
        catalog.close()


@pytest.mark.asyncio
async def test_http_chat_answers_four_metadata_followups_without_model_and_persists_facts(tmp_path, monkeypatch):
    from app import main as module

    provider = ScriptedProvider()
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
                "file": ("tickets.csv", b"created_at,ticket\n2024-10-01,A\n2024-10-03,B\n", "text/csv"),
            })
            source_id = upload.json()["source_id"]
            chat_id = None
            for question in (
                "Какие есть столбцы?",
                "Что ещё можешь скзаать про эти данные?",
                "А за какой период они и сколько их?",
                "А какие поля здесь?",
            ):
                path = "/agent/chat" + (f"?chat_id={chat_id}" if chat_id else "")
                response = await client.post(path, json={"question": question, "source_ids": [source_id]})
                assert response.status_code == 200
                data = response.json()
                assert data["status"] == "answered"
                assert data["answer_kind"] == "computed"
                assert data["timing"]["calls"] == []
                chat_id = data["chat_id"]
            assert provider.messages == []
            history = (await client.get(f"/chats/{chat_id}")).json()
            assert history["source_id"] == source_id
            assert len(history["messages"]) == 8
            assert all(message["analysis_payload"] for message in history["messages"] if message["role"] == "assistant")


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

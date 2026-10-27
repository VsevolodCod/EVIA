import pytest
import httpx

from app.agent import AgentRuntime
from app.llm.mock import MockLLMProvider
from app.schema_catalog import SchemaCatalog
from app.source_service import SourceService
from app.tools import build_tool_registry
from app.models import LLMResponse


@pytest.mark.asyncio
async def test_agent_calls_tool_and_returns_answer(tmp_path):
    catalog = SchemaCatalog(tmp_path / "catalog.sqlite3")

    source_service = SourceService(
        tmp_path / "data",
        catalog,
    )

    tools = build_tool_registry(
        catalog,
        source_service,
    )

    agent = AgentRuntime(
        llm=MockLLMProvider(),
        tools=tools,
        max_steps=3,
    )

    result = await agent.ask("Что есть в данных?")

    assert result.steps == 2
    assert len(result.tool_results) == 1
    assert result.tool_results[0].tool_name == "list_sources"
    assert result.tool_results[0].ok
    assert result.answer


@pytest.mark.asyncio
async def test_mock_agent_previews_selected_source_for_every_question(tmp_path):
    catalog = SchemaCatalog(tmp_path / "catalog.sqlite3")
    source_service = SourceService(tmp_path / "data", catalog)
    source = source_service.register_csv(
        filename="sales.csv",
        content=b"month,revenue\n2026-01,120\n2026-02,180\n",
    )
    agent = AgentRuntime(
        llm=MockLLMProvider(),
        tools=build_tool_registry(catalog, source_service),
        max_steps=3,
    )

    first = await agent.ask("Покажи выручку", [source.source_id])
    second = await agent.ask("Покажи ещё раз", [source.source_id])

    assert [item.tool_name for item in first.tool_results] == ["preview_data"]
    assert [item.tool_name for item in second.tool_results] == ["preview_data"]
    assert first.tool_results[0].data[0]["revenue"] == "120"


@pytest.mark.asyncio
async def test_history_is_optional_and_not_mutated(tmp_path):
    from app.models import ChatMessage, LLMResponse

    class RecordingLLM:
        def __init__(self):
            self.messages = []

        async def chat(self, messages, tools=None):
            self.messages = list(messages)
            return LLMResponse(content='answer')

    catalog = SchemaCatalog(tmp_path / 'catalog.db')
    try:
        llm = RecordingLLM()
        agent = AgentRuntime(llm, build_tool_registry(catalog, SourceService(tmp_path / 'data', catalog)))
        await agent.ask('first', ['source-A'])
        assert [message.role for message in llm.messages] == ['system', 'user']
        assert 'source-A' in llm.messages[-1].content
        history = [ChatMessage(role='user', content='earlier')]
        await agent.ask('next', ['source-B'], history=history)
        assert [message.content for message in llm.messages[1:]][0] == 'earlier'
        assert len(history) == 1
    finally:
        catalog.close()


@pytest.mark.asyncio
async def test_agent_continues_truncated_answer_before_reporting_success():
    class LLM:
        def __init__(self):
            self.messages = []

        async def chat(self, messages, tools=None):
            self.messages.append(list(messages))
            if len(self.messages) == 1:
                return LLMResponse(content='В данных 500 000', finish_reason='length')
            return LLMResponse(content=' строк за 2024 год.', finish_reason='stop')

    class Tools:
        def descriptions(self):
            return []

    llm = LLM()
    result = await AgentRuntime(llm, Tools(), max_steps=3).ask('Что в данных?')
    assert result.status == 'answered'
    assert result.answer == 'В данных 500 000 строк за 2024 год.'
    assert result.steps == 2
    assert result.timing and len(result.timing.calls) == 2


@pytest.mark.asyncio
async def test_agent_does_not_return_partial_answer_when_token_limit_exhausted():
    class LLM:
        async def chat(self, messages, tools=None):
            return LLMResponse(content='Обрыв', finish_reason='length')

    class Tools:
        def descriptions(self):
            return []

    result = await AgentRuntime(LLM(), Tools(), max_steps=2).ask('Вопрос')
    assert result.status == 'error'
    assert result.error and result.error.code == 'MODEL_OUTPUT_INCOMPLETE'
    assert 'Обрыв' not in result.answer
    assert result.steps == 2


@pytest.mark.asyncio
async def test_agent_rejects_empty_continuation_after_truncated_answer():
    class LLM:
        calls = 0

        async def chat(self, messages, tools=None):
            self.calls += 1
            if self.calls == 1:
                return LLMResponse(content="Период начинается с", finish_reason="length")
            return LLMResponse(content="", finish_reason="stop")

    class Tools:
        def descriptions(self): return []

    result = await AgentRuntime(LLM(), Tools(), max_steps=3).ask("Период?")
    assert result.status == "error"
    assert result.error and result.error.code == "MODEL_OUTPUT_INCOMPLETE"
    assert "Период начинается с" not in result.answer


@pytest.mark.asyncio
async def test_agent_retries_transient_502_without_spending_a_step(monkeypatch):
    class LLM:
        calls = 0

        async def chat(self, messages, tools=None):
            self.calls += 1
            if self.calls == 1:
                request = httpx.Request("POST", "https://model.example/chat")
                response = httpx.Response(502, request=request)
                raise httpx.HTTPStatusError("temporary", request=request, response=response)
            return LLMResponse(content="Ответ получен", finish_reason="stop")

    class Tools:
        def descriptions(self): return []

    async def no_wait(_delay):
        return None

    monkeypatch.setattr("app.agent.asyncio.sleep", no_wait)
    llm = LLM()
    result = await AgentRuntime(llm, Tools(), max_steps=1).ask("Вопрос")
    assert result.status == "answered"
    assert result.answer == "Ответ получен"
    assert result.steps == 1
    assert llm.calls == 2


@pytest.mark.asyncio
async def test_attached_dashboard_id_reaches_general_agent_context(tmp_path):
    class LLM:
        def __init__(self):
            self.messages = []

        async def chat(self, messages, tools=None):
            self.messages = list(messages)
            return LLMResponse(content="Готово", finish_reason="stop")

    catalog = SchemaCatalog(tmp_path / "catalog.db")
    sources = SourceService(tmp_path / "data", catalog)
    source = sources.register_csv("sales.csv", b"month;revenue\nJan;10\n")
    try:
        llm = LLM()
        agent = AgentRuntime(llm, build_tool_registry(catalog, sources), sources=sources)
        result = await agent.ask("Покажи текущий дашборд", [source.source_id], dashboard_id="dashboard-123")
        assert result.status == "answered"
        assert "dashboard-123" in llm.messages[-1].content
        assert source.source_id in llm.messages[-1].content
    finally:
        catalog.close()


@pytest.mark.asyncio
async def test_selected_csv_dashboard_uses_bounded_spec_and_computed_tool(tmp_path):
    import json

    class LLM:
        def __init__(self):
            self.schemas = []

        async def chat_structured(self, messages, schema):
            self.schemas.append(schema)
            return LLMResponse(content=json.dumps({
                "title": "Выручка",
                "cards": [{"type": "kpi", "title": "Сумма выручки", "field": "revenue", "aggregate": "sum"}],
            }), finish_reason="stop")

        async def chat(self, messages, tools=None):
            raise AssertionError("Dashboard should use structured specification")

    catalog = SchemaCatalog(tmp_path / "catalog.db")
    sources = SourceService(tmp_path / "data", catalog)
    source = sources.register_csv("sales.csv", b"id;revenue\n1;120,5\n2;180.5\n")
    llm = LLM()
    try:
        result = await AgentRuntime(llm, build_tool_registry(catalog, sources), sources=sources).ask(
            "Создай дашборд с KPI по сумме revenue", [source.source_id]
        )
        assert result.status == "answered"
        assert result.answer_kind == "computed"
        assert result.tool_results[0].tool_name == "create_dashboard"
        assert result.tool_results[0].data["cards"][0]["data"]["value"] == "301.0"
        card = result.tool_results[0].data["cards"][0]
        assert card["definition"]["field"] == {"source_id": source.source_id, "field": "revenue"}
        assert card["definition"]["aggregate"] == "sum"
        assert card["data"]["provenance"][0]["source_id"] == source.source_id
        assert llm.schemas[0]["properties"]["cards"]["maxItems"] == 2
    finally:
        catalog.close()


@pytest.mark.asyncio
async def test_failed_dashboard_does_not_claim_success(tmp_path):
    import json

    class LLM:
        async def chat_structured(self, messages, schema):
            return LLMResponse(content=json.dumps({
                "title": "Ошибка", "cards": [{"type": "kpi", "title": "Неверный агрегат",
                "field": "category", "aggregate": "sum"}],
            }), finish_reason="stop")

        async def chat(self, messages, tools=None):
            raise AssertionError("Dashboard should use structured specification")

    catalog = SchemaCatalog(tmp_path / "catalog.db")
    sources = SourceService(tmp_path / "data", catalog)
    source = sources.register_csv("sales.csv", b"category\nA\n")
    try:
        result = await AgentRuntime(LLM(), build_tool_registry(catalog, sources), sources=sources).ask(
            "Создай дашборд", [source.source_id]
        )
        assert result.status == "error"
        assert result.answer_kind != "computed"
        assert result.tool_results[0].tool_name == "create_dashboard"
    finally:
        catalog.close()


@pytest.mark.asyncio
async def test_dashboard_uses_schema_fallback_after_invalid_model_draft(tmp_path):
    class LLM:
        async def chat(self, messages, tools=None):
            return LLMResponse(content="Построю график по данным.", finish_reason="stop")

    catalog = SchemaCatalog(tmp_path / "catalog.db")
    sources = SourceService(tmp_path / "data", catalog)
    source = sources.register_csv(
        "sales.csv",
        b"month;revenue\nJan;120,5\nFeb;180,5\n",
    )
    try:
        result = await AgentRuntime(LLM(), build_tool_registry(catalog, sources), sources=sources).ask(
            "Построй дашборд", [source.source_id]
        )

        assert result.status == "answered"
        assert result.answer_kind == "computed"
        dashboard = result.tool_results[-1]
        assert dashboard.tool_name == "create_dashboard"
        assert dashboard.data["id"]
        assert [card["type"] for card in dashboard.data["cards"]] == ["kpi", "line"]
        assert all(card["status"] == "success" for card in dashboard.data["cards"])
    finally:
        catalog.close()


@pytest.mark.asyncio
async def test_dashboard_retries_undrawable_card_and_keeps_final_result(tmp_path):
    import json

    class LLM:
        def __init__(self):
            self.calls = 0

        async def chat_structured(self, messages, schema):
            self.calls += 1
            card = ({"type": "line", "title": "Статус", "x": "month", "y": "status", "aggregate": "max"}
                    if self.calls == 1 else
                    {"type": "kpi", "title": "Выручка", "field": "revenue", "aggregate": "sum"})
            return LLMResponse(content=json.dumps({"title": "Продажи", "cards": [card]}), finish_reason="stop")

    catalog = SchemaCatalog(tmp_path / "catalog.db")
    sources = SourceService(tmp_path / "data", catalog)
    source = sources.register_csv("sales.csv", b"month;status;revenue\nJan;Alpha;120,5\nFeb;Beta;180.5\n")
    llm = LLM()
    try:
        result = await AgentRuntime(llm, build_tool_registry(catalog, sources), sources=sources).ask(
            "Создай дашборд", [source.source_id]
        )
        assert result.status == "answered"
        assert result.answer_kind == "computed"
        assert llm.calls == 2
        assert [item.data["cards"][0]["status"] for item in result.tool_results] == ["error", "success"]
        assert result.tool_results[-1].data["cards"][0]["data"]["value"] == "301.0"
    finally:
        catalog.close()

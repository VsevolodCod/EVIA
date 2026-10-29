"""Issue #75: factual schema questions must work without model inference."""

import pytest

from app.agent import AgentRuntime
from app.models import LLMResponse
from app.schema_catalog import SchemaCatalog
from app.source_service import SourceService
from app.tools import build_tool_registry


class UnavailableModel:
    calls = 0

    async def chat(self, messages, tools=None):
        self.calls += 1
        raise AssertionError("Schema lookup must not call the model")


@pytest.mark.asyncio
@pytest.mark.parametrize("question", [
    "Какие есть столбцы?",
    "Назови колонки этого источника",
    "Покажи список полей",
    "Какая схема у выбранного CSV?",
])
async def test_schema_questions_use_current_source_without_llm(tmp_path, question):
    catalog = SchemaCatalog(tmp_path / "catalog.db")
    sources = SourceService(tmp_path / "data", catalog)
    source = sources.register_csv("sales.csv", b"month;revenue\nJanuary;10\n")
    model = UnavailableModel()
    try:
        agent = AgentRuntime(model, build_tool_registry(catalog, sources), sources=sources)
        answer = await agent.ask(question, [source.source_id])
        assert answer.status == "answered"
        assert answer.answer_kind == "computed"
        assert "month" in answer.answer and "revenue" in answer.answer
        assert [item.tool_name for item in answer.tool_results] == ["get_source_schema"]
        assert answer.timing and not answer.timing.calls
        assert model.calls == 0
    finally:
        catalog.close()


@pytest.mark.asyncio
async def test_schema_question_tracks_reimported_header_only_snapshot(tmp_path):
    catalog = SchemaCatalog(tmp_path / "catalog.db")
    sources = SourceService(tmp_path / "data", catalog)
    source = sources.register_csv("sales.csv", b"old_name\nvalue\n")
    model = UnavailableModel()
    try:
        updated = sources.register_csv("sales.csv", b"new_name;amount\n", source_id=source.source_id)
        answer = await AgentRuntime(model, build_tool_registry(catalog, sources), sources=sources).ask(
            "Какие поля есть?", [updated.source_id]
        )
        assert answer.status == "answered"
        assert "new_name" in answer.answer and "amount" in answer.answer
        assert "old_name" not in answer.answer
        assert answer.tool_results[0].data["version"] == updated.schema_version
        assert model.calls == 0
    finally:
        catalog.close()


@pytest.mark.asyncio
async def test_question_about_column_values_still_uses_model(tmp_path):
    catalog = SchemaCatalog(tmp_path / "catalog.db")
    sources = SourceService(tmp_path / "data", catalog)
    source = sources.register_csv("sales.csv", b"month;revenue\nJanuary;10\n")

    class Model:
        calls = 0

        async def chat(self, messages, tools=None):
            self.calls += 1
            return LLMResponse(content="Нужно посмотреть значения.")

    model = Model()
    try:
        answer = await AgentRuntime(model, build_tool_registry(catalog, sources), sources=sources).ask(
            "Какие значения в столбце revenue?", [source.source_id]
        )
        assert answer.answer_kind == "model"
        assert model.calls == 1
    finally:
        catalog.close()

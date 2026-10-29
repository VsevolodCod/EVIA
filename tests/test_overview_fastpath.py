"""Issue #75: basic source orientation must use current facts, even without an LLM."""

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
        raise AssertionError("Source overview must not call the model")


@pytest.mark.asyncio
@pytest.mark.parametrize("question", [
    "Что передо мной?",
    "Что есть в этих данных?",
    "что ещё можешь скзаать про эти данные?",
    "что ещё можешь сказать про эти данные?",
    "За какой период они и сколько их?",
])
async def test_general_overview_uses_current_full_profile(tmp_path, question):
    catalog = SchemaCatalog(tmp_path / "catalog.db")
    sources = SourceService(tmp_path / "data", catalog)
    source = sources.register_csv(
        "events.csv",
        b"period,revenue,segment\n2026-01-02,100,A\n2026-02-05,200,B\n2026-03-04,300,A\n",
    )
    model = UnavailableModel()
    try:
        answer = await AgentRuntime(
            model, build_tool_registry(catalog, sources), sources=sources
        ).ask(question, [source.source_id])
        assert answer.status == "answered"
        assert answer.answer_kind == "computed"
        assert "3 строки" in answer.answer
        assert "3 поля" in answer.answer
        assert all(name in answer.answer for name in ("period", "revenue", "segment"))
        assert "2026-01-02" in answer.answer and "2026-03-04" in answer.answer
        assert "обязатель" not in answer.answer.lower()
        assert [item.tool_name for item in answer.tool_results] == [
            "get_source_schema", "profile_data"
        ]
        assert answer.timing and not answer.timing.calls
        assert model.calls == 0
    finally:
        catalog.close()


@pytest.mark.asyncio
async def test_overview_does_not_mix_sources_or_stale_reimports(tmp_path):
    catalog = SchemaCatalog(tmp_path / "catalog.db")
    sources = SourceService(tmp_path / "data", catalog)
    first = sources.register_csv("first.csv", b"old_field\na\n")
    second = sources.register_csv("second.csv", b"second_field\nb\n")
    model = UnavailableModel()
    try:
        agent = AgentRuntime(model, build_tool_registry(catalog, sources), sources=sources)
        second_answer = await agent.ask("Что есть в этих данных?", [second.source_id])
        assert "second_field" in second_answer.answer
        assert "old_field" not in second_answer.answer

        updated = sources.register_csv("first.csv", b"new_field\n", source_id=first.source_id)
        first_answer = await agent.ask("Что передо мной?", [updated.source_id])
        assert "new_field" in first_answer.answer
        assert "0 строк" in first_answer.answer
        assert "old_field" not in first_answer.answer
        assert "second_field" not in first_answer.answer
        assert model.calls == 0
    finally:
        catalog.close()


@pytest.mark.asyncio
async def test_overview_rejects_reimport_between_schema_and_profile(tmp_path, monkeypatch):
    catalog = SchemaCatalog(tmp_path / "catalog.db")
    sources = SourceService(tmp_path / "data", catalog)
    source = sources.register_csv("events.csv", b"old_field\na\n")
    original_profile = sources.profile

    def reimport_then_profile(source_id):
        sources.register_csv("events.csv", b"new_field\nb\n", source_id=source_id)
        return original_profile(source_id)

    monkeypatch.setattr(sources, "profile", reimport_then_profile)
    model = UnavailableModel()
    try:
        answer = await AgentRuntime(
            model, build_tool_registry(catalog, sources), sources=sources
        ).ask("Что передо мной?", [source.source_id])
        assert answer.status == "error"
        assert answer.error and answer.error.retryable
        assert "old_field" not in answer.answer
        assert "new_field" not in answer.answer
        assert model.calls == 0
    finally:
        catalog.close()


@pytest.mark.asyncio
async def test_specific_filtered_question_still_uses_agent(tmp_path):
    catalog = SchemaCatalog(tmp_path / "catalog.db")
    sources = SourceService(tmp_path / "data", catalog)
    source = sources.register_csv("events.csv", b"period,revenue\n2026-01-02,100\n")

    class Model:
        calls = 0

        async def chat(self, messages, tools=None):
            self.calls += 1
            return LLMResponse(content="Требуется фильтрация.")

    model = Model()
    try:
        answer = await AgentRuntime(
            model, build_tool_registry(catalog, sources), sources=sources
        ).ask("Что есть в этих данных за 2025 год?", [source.source_id])
        assert answer.answer_kind == "model"
        assert model.calls == 1
    finally:
        catalog.close()

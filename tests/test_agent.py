import pytest

from app.agent import AgentRuntime
from app.llm.mock import MockLLMProvider
from app.schema_catalog import SchemaCatalog
from app.source_service import SourceService
from app.tools import build_tool_registry


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

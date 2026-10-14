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

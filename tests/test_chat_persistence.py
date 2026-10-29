import asyncio
import importlib

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import IntegrityError

from app.chat_manager import ChatManager, ChatNotFoundError
from app.db.chat.engine import create_chat_database, initialize_chat_database
from app.models import Chat, ChatMessage


@pytest.mark.asyncio
async def test_chat_records_origin_for_new_saved_dashboard(manager, api_source, monkeypatch):
    from app import main as module
    from app.contracts.v1 import AgentResponse
    from app.models import ToolResult

    recorded = []

    class Repository:
        def set_origin_chat(self, dashboard_id, chat_id):
            recorded.append((dashboard_id, chat_id))

    class Agent:
        async def ask(self, **_kwargs):
            return AgentResponse(
                request_id="origin-request", status="answered", answer="Отчёт сохранён", steps=1,
                tool_results=[ToolResult(tool_name="compose_dashboard", ok=True, data={
                    "success": True, "dashboard": {"id": "saved-dashboard"},
                })],
            )

    monkeypatch.setattr(module, "dashboard_repository", Repository())
    monkeypatch.setattr(module, "agent", Agent())
    monkeypatch.setattr(module.app.state, "chat_manager", manager, raising=False)
    async with AsyncClient(transport=ASGITransport(app=module.app), base_url="http://test") as client:
        response = await client.post("/agent/chat", json={
            "question": "Создай отчёт", "source_ids": [api_source],
        })
    assert response.status_code == 200
    assert recorded == [("saved-dashboard", response.json()["chat_id"])]


@pytest.fixture
def api_source(tmp_path, monkeypatch):
    from app import main as module
    from app.models import DataSource
    from app.schema_catalog import SchemaCatalog

    catalog = SchemaCatalog(tmp_path / 'selected-source.db')
    catalog.upsert_source(DataSource(source_id='test-source', name='Test', source_type='csv'))
    monkeypatch.setattr(module, 'catalog', catalog)
    yield 'test-source'
    catalog.close()


@pytest_asyncio.fixture
async def manager(tmp_path):
    engine, sessions = create_chat_database(tmp_path / 'chats.db')
    await initialize_chat_database(engine)
    try:
        yield ChatManager(sessions)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_repeat_chat_and_long_history_survive_restart(manager, tmp_path):
    chat = await manager.get_or_create(temporary=False)
    chat.messages = [ChatMessage(role='user', content=str(i)) for i in range(80)]
    await manager.save(chat)
    resumed = await manager.get_or_create(chat.chat_id, temporary=False)
    assert isinstance(resumed, Chat)
    assert not resumed.temporary
    assert len(resumed.messages) == 80
    resumed.messages.append(ChatMessage(role='assistant', content='new'))
    await manager.save(resumed)
    await manager.save(resumed)  # Same message IDs are idempotent.
    engine, sessions = create_chat_database(tmp_path / 'chats.db')
    try:
        reopened = await ChatManager(sessions).get_or_create(chat.chat_id, temporary=False)
        assert len(reopened.messages) == 81
        assert [m.content for m in reopened.messages[:80]] == [str(i) for i in range(80)]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_dashboard_result_survives_restart_and_old_chat_database_migrates(tmp_path):
    from sqlalchemy import text

    db_path = tmp_path / 'legacy-chats.db'
    engine, sessions = create_chat_database(db_path)
    async with engine.begin() as connection:
        await connection.execute(text('CREATE TABLE chats (chat_id VARCHAR(36) PRIMARY KEY, title VARCHAR(200) NOT NULL, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)'))
        await connection.execute(text('CREATE TABLE chat_messages (message_id VARCHAR(36) PRIMARY KEY, chat_id VARCHAR(36) NOT NULL, position INTEGER NOT NULL, role VARCHAR(20) NOT NULL, content TEXT NOT NULL, name VARCHAR(200), tool_call_id VARCHAR(200), tool_calls JSON, created_at DATETIME NOT NULL)'))
    await initialize_chat_database(engine)
    manager = ChatManager(sessions)
    chat = await manager.get_or_create(temporary=False)
    response = {'answer': 'Построено карточек: 1.', 'steps': 1, 'status': 'answered', 'answer_kind': 'computed',
                'tool_results': [{'tool_name': 'create_dashboard', 'ok': True,
                                  'data': {'version': 1, 'title': 'Выручка', 'cards': []}, 'error': None}]}
    chat.messages.append(ChatMessage(role='assistant', content=response['answer'], response=response))
    await manager.save(chat)
    await engine.dispose()

    reopened_engine, reopened_sessions = create_chat_database(db_path)
    await initialize_chat_database(reopened_engine)
    try:
        restored = await ChatManager(reopened_sessions).get_or_create(chat.chat_id, temporary=False)
        assert restored.messages[0].response == response
    finally:
        await reopened_engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_writers_from_separate_connections_preserve_messages(manager, tmp_path):
    chat = await manager.get_or_create(temporary=False)
    engine, sessions = create_chat_database(tmp_path / 'chats.db')
    other = ChatManager(sessions)
    try:
        snapshots = [await manager.get_or_create(chat.chat_id, temporary=False) for _ in range(12)]
        for i, snapshot in enumerate(snapshots):
            snapshot.messages.append(ChatMessage(role='user', content=f'parallel-{i}'))
        await asyncio.gather(*[(manager if i % 2 else other).save(snapshot) for i, snapshot in enumerate(snapshots)])
        saved = await manager.get_or_create(chat.chat_id, temporary=False)
        assert len(saved.messages) == 12
        assert {m.content for m in saved.messages} == {f'parallel-{i}' for i in range(12)}
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_cursor_pagination_is_stable_while_new_messages_arrive(manager):
    chat = await manager.get_or_create(temporary=False)
    chat.messages = [ChatMessage(role='user', content=str(i)) for i in range(75)]
    await manager.save(chat)
    first = await manager.get_persistent_chat(chat.chat_id, limit=50)
    assert [m.content for m in first.messages] == [str(i) for i in range(25, 75)]
    assert first.next_before == 25
    chat.messages.append(ChatMessage(role='user', content='75'))
    await manager.save(chat)
    second = await manager.get_persistent_chat(chat.chat_id, limit=50, before=first.next_before)
    assert [m.content for m in second.messages] == [str(i) for i in range(25)]
    assert second.next_before is None
    assert not second.has_more
    assert not ({m.message_id for m in first.messages} & {m.message_id for m in second.messages})


@pytest.mark.asyncio
async def test_failed_save_rolls_back_all_new_messages_and_metadata(manager):
    first = await manager.get_or_create(temporary=False)
    existing = ChatMessage(role='user', content='first chat')
    first.messages.append(existing)
    await manager.save(first)
    second = await manager.get_or_create(temporary=False)
    second.title = 'must roll back'
    second.messages = [ChatMessage(role='user', content='must roll back'), existing]
    with pytest.raises((IntegrityError, ValueError)):
        await manager.save(second)
    saved = await manager.get_or_create(second.chat_id, temporary=False)
    assert saved.messages == []
    assert saved.title != 'must roll back'
    assert len((await manager.get_or_create(first.chat_id, temporary=False)).messages) == 1


@pytest.mark.asyncio
async def test_temporary_chat_is_detached_and_not_persisted(manager):
    chat = await manager.get_or_create(temporary=True)
    chat.messages.append(ChatMessage(role='user', content='not saved yet'))
    assert (await manager.get_or_create(chat.chat_id, temporary=True)).messages == []
    await manager.save(chat)
    assert len((await manager.get_or_create(chat.chat_id, temporary=True)).messages) == 1
    assert await manager.get_persistent_chat(chat.chat_id) is None
    with pytest.raises(ChatNotFoundError):
        await ChatManager(manager.session_factory).get_or_create(chat.chat_id, temporary=True)


@pytest.mark.asyncio
async def test_api_first_and_second_ask_and_failed_model_leave_valid_history(tmp_path, monkeypatch, api_source):
    monkeypatch.setenv('BI_DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.setenv('CATALOG_DB_PATH', str(tmp_path / 'catalog.db'))
    monkeypatch.setenv('CHAT_DB_PATH', str(tmp_path / 'api-chats.db'))
    module = importlib.import_module('app.main')
    monkeypatch.setattr(module.settings, 'chat_db_path', tmp_path / 'api-chats.db')
    from app.agent import AgentRuntime
    from app.llm.mock import MockLLMProvider
    from app.tools import ToolRegistry
    monkeypatch.setattr(module, 'agent', AgentRuntime(MockLLMProvider(), ToolRegistry()))
    async with module.app.router.lifespan_context(module.app), AsyncClient(transport=ASGITransport(app=module.app), base_url='http://test') as client:
        first = await client.post('/agent/chat', json={'question': 'first', 'source_ids': [api_source]})
        assert first.status_code == 200
        chat_id = first.json()['chat_id']
        second = await client.post('/agent/chat', params={'chat_id': chat_id}, json={'question': 'second'})
        assert second.status_code == 200
        history = (await client.get(f'/chats/{chat_id}')).json()
        assert [m['role'] for m in history['messages']] == ['user', 'assistant', 'user', 'assistant']
        assert history['total_messages'] == 4
        async def fail(**kwargs):
            raise RuntimeError('synthetic model outage')
        monkeypatch.setattr(module.agent, 'ask', fail)
        failed = await client.post('/agent/chat', params={'chat_id': chat_id}, json={'question': 'failure'})
        assert failed.status_code == 502
        history = (await client.get(f'/chats/{chat_id}')).json()
        assert history['total_messages'] == 5
        assert history['messages'][-1]['content'] == 'failure'
        assert history['messages'][-1]['role'] == 'user'
        monkeypatch.setattr(module, 'agent', AgentRuntime(MockLLMProvider(), ToolRegistry()))
        responses = await asyncio.gather(*[
            client.post('/agent/chat', params={'chat_id': chat_id}, json={'question': question})
            for question in ('parallel A', 'parallel B')])
        assert [response.status_code for response in responses] == [200, 200]
        history = (await client.get(f'/chats/{chat_id}')).json()
        assert history['total_messages'] == 9
        assert {m['content'] for m in history['messages'] if m['role'] == 'user'} >= {'parallel A', 'parallel B'}
        assert (await client.get(f'/chats/{chat_id}?before=0')).json()['messages'] == []
        assert (await client.get(f'/chats/{chat_id}?before=2&offset=1')).status_code == 400
        assert (await client.delete(f'/chats/{chat_id}')).status_code == 204
        assert (await client.get(f'/chats/{chat_id}')).status_code == 404


@pytest.mark.asyncio
async def test_stale_partial_snapshot_can_append_but_not_erase_or_edit(manager):
    chat = await manager.get_or_create(temporary=False)
    chat.messages = [ChatMessage(role='user', content=str(i)) for i in range(60)]
    await manager.save(chat)
    partial = chat.model_copy(deep=True)
    partial.messages = partial.messages[-5:] + [ChatMessage(role='assistant', content='appended')]
    await manager.save(partial)
    saved = await manager.get_or_create(chat.chat_id, temporary=False)
    assert len(saved.messages) == 61
    saved.messages[0].content = 'rewrite denied'
    with pytest.raises(ValueError, match='immutable'):
        await manager.save(saved)
    assert (await manager.get_or_create(chat.chat_id, temporary=False)).messages[0].content == '0'


@pytest.mark.asyncio
async def test_duplicate_create_is_rejected_without_changing_chat(manager):
    chat = await manager.get_or_create(temporary=False)
    duplicate = chat.model_copy(update={'title': 'replacement'})
    with pytest.raises(ValueError, match='already exists'):
        await manager.create_persistent_chat(duplicate)
    assert (await manager.get_or_create(chat.chat_id, temporary=False)).title == chat.title


@pytest.mark.asyncio
async def test_follow_up_receives_previous_turns_and_new_chat_starts_empty(tmp_path, monkeypatch, api_source):
    monkeypatch.setenv('BI_DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.setenv('CATALOG_DB_PATH', str(tmp_path / 'catalog.db'))
    monkeypatch.setenv('CHAT_DB_PATH', str(tmp_path / 'api-chats.db'))
    module = importlib.import_module('app.main')
    monkeypatch.setattr(module.settings, 'chat_db_path', tmp_path / 'api-chats.db')
    from app.models import AskResponse
    seen = []
    class RecordingAgent:
        async def ask(self, question, source_ids, history):
            seen.append([(m.role, m.content) for m in history])
            return AskResponse(answer=f'Answer: {question}', steps=1)
    monkeypatch.setattr(module, 'agent', RecordingAgent())
    async with module.app.router.lifespan_context(module.app), AsyncClient(transport=ASGITransport(app=module.app), base_url='http://test') as client:
        first_id = (await client.post('/chats', json={'title': 'First'})).json()['chat_id']
        second_id = (await client.post('/chats', json={'title': 'Second'})).json()['chat_id']
        for chat_id, question in [(first_id, 'remember 73'), (first_id, 'what number?'), (second_id, 'new context')]:
            response = await client.post('/agent/chat', params={'chat_id': chat_id}, json={'question': question, 'source_ids': [api_source]})
            assert response.status_code == 200
            assert response.json()['chat_id'] == chat_id
        assert seen == [[], [('user', 'remember 73'), ('assistant', 'Answer: remember 73')], []]


@pytest.mark.asyncio
async def test_failed_agent_answer_is_not_saved_as_successful_assistant_message(tmp_path, monkeypatch, api_source):
    monkeypatch.setenv('BI_DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.setenv('CATALOG_DB_PATH', str(tmp_path / 'catalog.db'))
    monkeypatch.setenv('CHAT_DB_PATH', str(tmp_path / 'api-chats.db'))
    module = importlib.import_module('app.main')
    monkeypatch.setattr(module.settings, 'chat_db_path', tmp_path / 'api-chats.db')
    from app.contracts.v1 import AgentResponse, Error

    class FailingAgent:
        async def ask(self, question, source_ids, history):
            request_id = 'failed-request'
            return AgentResponse(
                request_id=request_id, status='error', answer='Модель недоступна.', steps=1,
                error=Error(code='MODEL_UNAVAILABLE', message='Модель недоступна.', request_id=request_id),
            )

    monkeypatch.setattr(module, 'agent', FailingAgent())
    async with module.app.router.lifespan_context(module.app), AsyncClient(transport=ASGITransport(app=module.app), base_url='http://test') as client:
        chat_id = (await client.post('/chats', json={'title': 'Test'})).json()['chat_id']
        answer = await client.post('/agent/chat', params={'chat_id': chat_id}, json={'question': 'Сколько строк?', 'source_ids': [api_source]})
        assert answer.status_code == 200
        assert answer.json()['status'] == 'error'
        history = (await client.get(f'/chats/{chat_id}')).json()
        assert [(message['role'], message['content']) for message in history['messages']] == [('user', 'Сколько строк?')]

import asyncio
import json
import sqlite3

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.chat_repository import ChatManager
from app.db.chat.engine import create_chat_database, initialize_chat_database
from app.models import ChatMessage, LLMResponse


@pytest_asyncio.fixture
async def repository(tmp_path):
    engine, sessions = create_chat_database(tmp_path / 'chat.db')
    await initialize_chat_database(engine)
    try:
        yield ChatManager(sessions)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_old_schema_migrates_twice_without_rewriting_legacy_history(tmp_path):
    path = tmp_path / 'legacy.db'
    with sqlite3.connect(path) as connection:
        connection.executescript('''
            CREATE TABLE chats (chat_id TEXT PRIMARY KEY, title TEXT NOT NULL,
                created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL);
            CREATE TABLE chat_messages (message_id TEXT PRIMARY KEY, chat_id TEXT NOT NULL,
                position INTEGER NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL,
                name TEXT, tool_call_id TEXT, tool_calls JSON, created_at DATETIME NOT NULL);
            INSERT INTO chats VALUES ('old', 'Legacy', '2026-01-01', '2026-01-01');
            INSERT INTO chat_messages VALUES ('message', 'old', 0, 'assistant',
                'Original text', NULL, NULL, NULL, '2026-01-01');
        ''')
    engine, sessions = create_chat_database(path)
    try:
        await initialize_chat_database(engine)
        await initialize_chat_database(engine)
        history = await ChatManager(sessions).get_persistent_chat('old')
        assert history.model_dump().get('source_id', 'absent') is None
        assert history.messages[0].model_dump().get('analysis_payload', 'absent') is None
        assert history.messages[0].content == 'Original text'
        with sqlite3.connect(path) as connection:
            assert {'source_id'} <= {row[1] for row in connection.execute('PRAGMA table_info(chats)')}
            assert {'analysis_payload'} <= {row[1] for row in connection.execute('PRAGMA table_info(chat_messages)')}
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('temporary', [False, True])
async def test_analysis_payload_is_detached_immutable_and_saved_atomically(repository, temporary):
    chat = await repository.get_or_create(temporary=temporary)
    payload = {'version': 1, 'response': {'request_id': 'original', 'results': [{'rows': [[300]]}]}}
    chat.messages.append(ChatMessage(role='assistant', content='300', analysis_payload=payload))
    await repository.save(chat)
    saved = await repository.get_or_create(chat.chat_id, temporary=temporary)
    assert saved.messages[0].model_dump().get('analysis_payload') == payload
    modified = saved.model_copy(deep=True)
    modified.messages[0].analysis_payload.response['results'][0]['rows'][0][0] = 999
    modified.messages.append(ChatMessage(role='user', content='must roll back'))
    with pytest.raises(ValueError, match='immutable'):
        await repository.save(modified)
    reloaded = await repository.get_or_create(chat.chat_id, temporary=temporary)
    assert len(reloaded.messages) == 1
    assert reloaded.messages[0].model_dump()['analysis_payload'] == payload


@pytest.mark.asyncio
@pytest.mark.parametrize('temporary', [False, True])
async def test_first_source_binding_is_atomic_and_stale_save_cannot_clear_it(repository, tmp_path, temporary):
    chat = await repository.get_or_create(temporary=temporary)
    engine, sessions = create_chat_database(tmp_path / 'chat.db')
    other = repository if temporary else ChatManager(sessions)
    try:
        results = await asyncio.gather(
            repository.bind_source(chat.chat_id, 'source-a', temporary=temporary),
            other.bind_source(chat.chat_id, 'source-b', temporary=temporary),
            return_exceptions=True,
        )
        assert sum(isinstance(result, str) for result in results) == 1
        assert sum(type(result).__name__ == 'ChatSourceConflictError' for result in results) == 1
        selected = next(result for result in results if isinstance(result, str))
        chat.messages.append(ChatMessage(role='user', content='stale append'))
        await repository.save(chat)
        assert (await repository.get_or_create(chat.chat_id, temporary=temporary)).source_id == selected
        assert await other.bind_source(chat.chat_id, None, temporary=temporary) == selected
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_unknown_payload_version_preserves_readable_text(repository):
    from sqlalchemy import update
    from app.db.chat.models import ChatMessageORM

    chat = await repository.get_or_create(temporary=False)
    chat.messages.append(ChatMessage(role='assistant', content='Readable archived answer'))
    await repository.save(chat)
    future_payload = {'version': 2, 'response': {'future': 'format'}}
    async with repository.session_factory.begin() as session:
        await session.execute(update(ChatMessageORM).values(analysis_payload=future_payload))
    history = await repository.get_persistent_chat(chat.chat_id)
    assert history.messages[0].content == 'Readable archived answer'
    assert history.messages[0].model_dump()['analysis_payload'] == future_payload


@pytest.mark.asyncio
async def test_first_requests_race_and_conflict_finishes_while_generation_is_waiting(tmp_path, monkeypatch):
    from app import main as module
    from app.models import AskResponse, DataSource
    from app.schema_catalog import SchemaCatalog

    catalog = SchemaCatalog(tmp_path / 'catalog.db')
    for source_id in ('first', 'second'):
        catalog.upsert_source(DataSource(source_id=source_id, name=source_id, source_type='csv'))
    monkeypatch.setattr(module, 'catalog', catalog)
    monkeypatch.setattr(module.settings, 'chat_db_path', tmp_path / 'chat.db')
    entered = asyncio.Event()
    finish = asyncio.Event()
    seen = []

    class WaitingAgent:
        async def ask(self, question, source_ids, history):
            seen.append(source_ids)
            entered.set()
            await finish.wait()
            return AskResponse(answer='Winner', steps=1)

    monkeypatch.setattr(module, 'agent', WaitingAgent())
    async with module.app.router.lifespan_context(module.app), AsyncClient(transport=ASGITransport(app=module.app), base_url='http://test') as client:
        chat_id = (await client.post('/chats', json={'title': 'Race'})).json()['chat_id']
        endpoint = f'/agent/chat?chat_id={chat_id}'
        tasks = [asyncio.create_task(client.post(endpoint, json={'question': source_id, 'source_ids': [source_id]}))
                 for source_id in ('first', 'second')]
        try:
            await asyncio.wait_for(entered.wait(), timeout=2)
            done, _ = await asyncio.wait(tasks, timeout=2, return_when=asyncio.FIRST_COMPLETED)
            assert len(done) == 1, 'Conflict must not wait for the winning LLM request'
            assert next(iter(done)).result().status_code == 409
            history = (await client.get(f'/chats/{chat_id}')).json()
            assert history['source_id'] == seen[0][0]
            assert [message['content'] for message in history['messages']] == [seen[0][0]]
            assert len(seen) == 1
        finally:
            finish.set()
            responses = await asyncio.gather(*tasks)
        assert sorted(response.status_code for response in responses) == [200, 409]


@pytest.mark.asyncio
async def test_invalid_response_and_missing_source_never_save_success_artifacts(tmp_path, monkeypatch):
    from app import main as module
    from app.models import AskResponse, DataSource
    from app.schema_catalog import SchemaCatalog

    catalog = SchemaCatalog(tmp_path / 'catalog.db')
    catalog.upsert_source(DataSource(source_id='valid', name='Valid', source_type='csv'))
    monkeypatch.setattr(module, 'catalog', catalog)
    monkeypatch.setattr(module.settings, 'chat_db_path', tmp_path / 'chat.db')
    seen = []

    class InvalidAgent:
        async def ask(self, **kwargs):
            seen.append(kwargs)
            return AskResponse.model_construct(answer=None, steps=1)

    monkeypatch.setattr(module, 'agent', InvalidAgent())
    async with module.app.router.lifespan_context(module.app), AsyncClient(transport=ASGITransport(app=module.app), base_url='http://test') as client:
        chat_id = (await client.post('/chats', json={'title': 'Validation'})).json()['chat_id']
        endpoint = f'/agent/chat?chat_id={chat_id}'
        for ids, status in [([], 400), (['valid', 'other'], 400), (['missing'], 404)]:
            result = await client.post(endpoint, json={'question': 'Rejected', 'source_ids': ids})
            assert result.status_code == status
            history = (await client.get(f'/chats/{chat_id}')).json()
            assert history['source_id'] is None
            assert history['messages'] == []
            assert seen == []
        invalid = await client.post(endpoint, json={'question': 'Invalid answer', 'source_ids': ['valid']})
        assert invalid.status_code == 400
        history = (await client.get(f'/chats/{chat_id}')).json()
        assert len(history['messages']) == 1
        assert history['messages'][0]['analysis_payload'] is None
        assert history['messages'][0]['role'] == 'user'


@pytest.mark.asyncio
async def test_chat_analysis_roundtrip_restart_source_changes_and_conflicts(tmp_path, monkeypatch):
    from app import main as module
    from app.agent import AgentRuntime
    from app.schema_catalog import SchemaCatalog
    from app.source_service import SourceService
    from app.tools import build_tool_registry

    class Provider:
        calls = 0
        histories = []

        async def chat(self, messages, tools=None):
            self.calls += 1
            self.histories.append([message.model_dump() for message in messages])
            if messages[-1].role == 'tool':
                return LLMResponse(content='Сумма рассчитана по выбранному источнику.')
            from app.models import ToolCall
            return LLMResponse(tool_calls=[ToolCall(name='query_data', arguments={
                'source_id': source.source_id,
                'sql': 'SELECT SUM(TRY_CAST(revenue AS BIGINT)) AS total FROM source',
            })], finish_reason='tool_calls')

    catalog = SchemaCatalog(tmp_path / 'catalog.db')
    sources = SourceService(tmp_path / 'data', catalog)
    source = sources.register_csv('sales.csv', b'month,revenue\n2026-01,120\n2026-02,180\n')
    other = sources.register_csv('other.csv', b'month,revenue\n2026-01,999\n')
    provider = Provider()
    monkeypatch.setattr(module, 'catalog', catalog)
    monkeypatch.setattr(module, 'source_service', sources)
    monkeypatch.setattr(module, 'agent', AgentRuntime(provider, build_tool_registry(catalog, sources), sources=sources))
    monkeypatch.setattr(module.settings, 'chat_db_path', tmp_path / 'chat.db')
    async with module.app.router.lifespan_context(module.app), AsyncClient(transport=ASGITransport(app=module.app), base_url='http://test') as client:
        chat_id = (await client.post('/chats', json={'title': 'Sales'})).json()['chat_id']
        endpoint = f'/agent/chat?chat_id={chat_id}'
        unbound = await client.post(endpoint, json={'question': 'Total?'})
        assert unbound.status_code == 400
        assert (await client.get(f'/chats/{chat_id}')).json()['total_messages'] == 0
        result = await client.post(endpoint, json={'question': 'Total?', 'source_ids': [source.source_id]})
        assert result.status_code == 200
        answer = result.json()
        assert answer['results'][0]['rows'] == [[300]]
        assert answer['timing']['elapsed_ms'] > 0
        assert answer['tool_results'][0]['tool_name'] == 'query_data'
        assert answer['results'][0]['provenance']
        history = (await client.get(f'/chats/{chat_id}')).json()
        assert history['source_id'] == source.source_id
        assert history['messages'][0]['analysis_payload'] is None
        assert history['messages'][1]['analysis_payload'] == {'version': 1, 'response': answer}
        assert (await client.get('/chats')).json()[0]['source_id'] == source.source_id
        switched = await client.post(endpoint, json={'question': 'Other?', 'source_ids': [other.source_id]})
        assert switched.status_code == 409
        assert provider.calls == 2
        assert (await client.get(f'/chats/{chat_id}')).json() == history
        # A fresh connection/manager must restore the exact artifact, without re-execution.
        engine, sessions = create_chat_database(tmp_path / 'chat.db')
        try:
            module.app.state.chat_manager = ChatManager(sessions)
            assert (await client.get(f'/chats/{chat_id}')).json() == history
            sources.register_csv('sales.csv', b'month,revenue\n2026-01,999\n', source_id=source.source_id)
            followup = await client.post(endpoint, json={'question': 'Again?'})
            assert followup.status_code == 200
            assert followup.json()['results'][0]['rows'] == [[999]]
            assert followup.json()['results'][0]['provenance'] != answer['results'][0]['provenance']
            assert all('analysis_payload' not in message for message in provider.histories[-1])
            # Removing a source still permits archived history and original snapshot reads.
            from sqlalchemy import delete
            from app.db.catalog.models import DataSourceORM
            with catalog.session_factory.begin() as session:
                session.execute(delete(DataSourceORM).where(DataSourceORM.source_id == source.source_id))
            archived = (await client.get(f'/chats/{chat_id}')).json()
            assert archived['messages'][1]['analysis_payload']['response'] == answer
            missing = await client.post(endpoint, json={'question': 'Now?'})
            assert missing.json()['status'] == 'error'
            assert (await client.get(f'/chats/{chat_id}')).json()['messages'][-1]['role'] == 'user'
            assert provider.calls == 4
        finally:
            await engine.dispose()

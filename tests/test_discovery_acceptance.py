"""Real HTTP/CSV/SQLite/DuckDB with scripted model tool choices, not live inference."""
import json
from unittest.mock import Mock
from httpx import ASGITransport, AsyncClient
import pytest
from app.agent import AgentRuntime
from app.models import LLMResponse, ToolCall
from app.schema_catalog import SchemaCatalog
from app.source_service import SourceService
from app.tools import build_tool_registry


@pytest.mark.asyncio
async def test_profile_and_tool_chat_sequence_preserve_data_and_history(tmp_path, monkeypatch, scripted_llm):
    from app import main as module
    catalog = SchemaCatalog(tmp_path / 'catalog.db')
    sources = SourceService(tmp_path / 'data', catalog)
    scans = Mock(wraps=sources.data_engine.profile)
    monkeypatch.setattr(sources.data_engine, 'profile', scans)
    monkeypatch.setattr(module, 'catalog', catalog)
    monkeypatch.setattr(module, 'source_service', sources)
    llm = scripted_llm([])
    monkeypatch.setattr(module, 'agent', AgentRuntime(llm, build_tool_registry(catalog, sources), sources=sources))
    monkeypatch.setattr(module.settings, 'chat_db_path', tmp_path / 'chat.db')
    def add_tool(name, source_id, sql=None):
        args = {'source_id': source_id}
        if sql: args['sql'] = sql
        llm.responses.extend([
            LLMResponse(tool_calls=[ToolCall(name=name, arguments=args)], finish_reason='tool_calls'),
            lambda messages: LLMResponse(content='Проверенные сведения: ' + json.dumps(json.loads(messages[-1].content)['data'], ensure_ascii=False)),
        ])
    async with module.app.router.lifespan_context(module.app):
        async with AsyncClient(transport=ASGITransport(app=module.app), base_url='http://test') as client:
            uploaded = await client.post('/sources/csv', files={'file': ('synthetic.csv',
                b'id;event_date;category;amount\n001;2024-01-01;A;1,5\n002;2024-02-03;B;2\n002;2024-02-03;B;2\n', 'text/csv')})
            assert uploaded.status_code == 200
            source_id = uploaded.json()['source_id']
            profile = await client.get(f'/sources/{source_id}/profile')
            assert profile.status_code == 200 and profile.json()['processed_rows'] == 3
            questions = [
                ('Что передо мной?', 'profile_data', None),
                ('Что есть в этих данных?', 'profile_data', None),
                ('Какие есть столбцы?', 'get_source_schema', None),
                ('А какие значения встречаются чаще всего?', 'query_data', 'SELECT COUNT(*) AS frequency, category FROM source GROUP BY category ORDER BY frequency DESC'),
                ('А теперь есть ли тут дубликаты?', 'query_data', 'SELECT COUNT(*) AS groups, SUM(n-1) AS extra FROM (SELECT COUNT(*) AS n FROM source GROUP BY id, event_date, category, amount HAVING COUNT(*) > 1) repeated'),
                ('А теперь покажи первые строки', 'query_data', 'SELECT * FROM source LIMIT 10'),
                ('Что ещё можешь скзаать про эти данные?', 'profile_data', None),
            ]
            chat_id = None
            for question, tool, sql in questions:
                add_tool(tool, source_id, sql)
                path = '/agent/chat' + (f'?chat_id={chat_id}' if chat_id else '')
                response = await client.post(path, json={'question': question, 'source_ids': [source_id]})
                assert response.status_code == 200, response.text
                body = response.json()
                assert body['status'] == 'answered'
                assert body['tool_results'][0]['tool_name'] == tool
                assert len(body['timing']['calls']) == 2
                assert chat_id is None or body['chat_id'] == chat_id
                chat_id = body['chat_id']
                if 'часто' in question:
                    assert body['results'][0]['rows'] == [[2, 'B'], [1, 'A']]
                elif 'дубликаты' in question:
                    assert body['results'][0]['rows'] == [[1, 1]]
                elif 'первые строки' in question:
                    assert body['results'][0]['rows'][0][0] == '001'
                if tool == 'query_data':
                    assert body['results'][0]['provenance'][0]['source_id'] == source_id
            assert scans.call_count == 1
            history = (await client.get(f'/chats/{chat_id}')).json()
            assert history['source_id'] == source_id
            assert len(history['messages']) == 2 * len(questions)
            saved = [m['analysis_payload']['response'] for m in history['messages'] if m['role'] == 'assistant']
            assert [r['tool_results'][0]['tool_name'] for r in saved] == [tool for _, tool, _ in questions]
            other = await client.post('/sources/csv', files={'file': ('other.csv', b'other_field\nZ\n', 'text/csv')})
            other_id = other.json()['source_id']
            conflict = await client.post(f'/agent/chat?chat_id={chat_id}', json={'question': 'Что передо мной?', 'source_ids': [other_id]})
            assert conflict.status_code == 409
            add_tool('get_source_schema', other_id)
            fresh = await client.post('/agent/chat', json={'question': 'Что передо мной?', 'source_ids': [other_id]})
            assert fresh.json()['chat_id'] != chat_id
            assert 'other_field' in fresh.json()['answer']
            assert 'event_date' not in fresh.json()['answer']
            assert not llm.responses

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
    def add_tool(name, args):
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
            def ref(field):
                return {'source_id': source_id, 'field': field}

            frequencies = {'definition': {
                'type': 'bar', 'title': 'Frequencies',
                'x': {**ref('category'), 'sort': 'label_asc'},
                'y': {**ref('category'), 'aggregate': 'count'},
            }}
            rows = {'definition': {
                'type': 'table', 'title': 'Rows',
                'fields': [ref(field) for field in ('id', 'event_date', 'category', 'amount')],
                'limit': 10,
            }}
            profile = await client.get(f'/sources/{source_id}/profile')
            assert profile.status_code == 200 and profile.json()['processed_rows'] == 3
            questions = [
                ('Что передо мной?', 'profile_data', None),
                ('Что есть в этих данных?', 'profile_data', None),
                ('Какие есть столбцы?', 'get_source_schema', None),
                ('А какие значения встречаются чаще всего?', 'build_chart', frequencies),
                ('А теперь есть ли тут дубликаты?', 'build_chart', rows),
                ('А теперь покажи первые строки', 'build_chart', rows),
                ('Что ещё можешь скзаать про эти данные?', 'profile_data', None),
            ]
            direct_questions = {
                'Что передо мной?', 'Что есть в этих данных?',
                'Какие есть столбцы?', 'Что ещё можешь скзаать про эти данные?',
            }
            chat_id = None
            for question, tool, args in questions:
                if question not in direct_questions:
                    add_tool(tool, args)
                path = '/agent/chat' + (f'?chat_id={chat_id}' if chat_id else '')
                response = await client.post(path, json={'question': question, 'source_ids': [source_id]})
                assert response.status_code == 200, response.text
                body = response.json()
                assert body['status'] == 'answered'
                first_tool = 'get_source_schema' if question in direct_questions else tool
                assert body['tool_results'][0]['tool_name'] == first_tool
                assert len(body['timing']['calls']) == (0 if question in direct_questions else 2)
                assert chat_id is None or body['chat_id'] == chat_id
                chat_id = body['chat_id']
                if tool == 'build_chart':
                    built = body['tool_results'][0]['data']
                    assert built['success']
                    assert built['result']['provenance'][0]['source_id'] == source_id
                if 'чаще' in question:
                    assert built['result']['points'] == [{'x': 'A', 'y': 1}, {'x': 'B', 'y': 2}]
                elif 'дубликаты' in question:
                    calculated_rows = built['result']['rows']
                    assert len(calculated_rows) == 3
                    assert calculated_rows[1] == calculated_rows[2]
                    assert calculated_rows[0] != calculated_rows[1]
                elif 'первые строки' in question:
                    assert built['result']['rows'][0]['id'] == '001'
            assert scans.call_count == 1
            history = (await client.get(f'/chats/{chat_id}')).json()
            assert history['source_id'] == source_id
            # Seven user/final-answer pairs and three assistant/tool pairs.
            assert len(history['messages']) == 2 * len(questions) + 2 * 3
            saved = [m['analysis_payload']['response'] for m in history['messages'] if m['role'] == 'assistant' and m["content"]]
            assert [r['tool_results'][0]['tool_name'] for r in saved] == [
                'get_source_schema' if question in direct_questions else tool
                for question, tool, _ in questions
            ]
            other = await client.post('/sources/csv', files={'file': ('other.csv', b'other_field\nZ\n', 'text/csv')})
            other_id = other.json()['source_id']
            conflict = await client.post(f'/agent/chat?chat_id={chat_id}', json={'question': 'Что передо мной?', 'source_ids': [other_id]})
            assert conflict.status_code == 409
            fresh = await client.post('/agent/chat', json={'question': 'Что передо мной?', 'source_ids': [other_id]})
            assert fresh.json()['chat_id'] != chat_id
            assert 'other_field' in fresh.json()['answer']
            assert 'event_date' not in fresh.json()['answer']
            assert not llm.responses

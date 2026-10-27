"""Real API/CSV/SQLite/DuckDB; provider fails if a basic action invokes inference."""
from unittest.mock import Mock

from httpx import ASGITransport, AsyncClient
import pytest

from app.agent import AgentRuntime
from app.schema_catalog import SchemaCatalog
from app.source_service import SourceService
from app.tools import build_tool_registry


class UnavailableInference:
    async def chat(self, *args, **kwargs):
        raise AssertionError('Basic discovery must remain available without inference')


@pytest.mark.asyncio
async def test_profile_endpoint_and_consecutive_chat_questions_reuse_verified_facts(tmp_path, monkeypatch):
    from app import main as module

    catalog = SchemaCatalog(tmp_path / 'catalog.db')
    sources = SourceService(tmp_path / 'data', catalog)
    scans = Mock(wraps=sources.data_engine.profile)
    monkeypatch.setattr(sources.data_engine, 'profile', scans)
    monkeypatch.setattr(module, 'catalog', catalog)
    monkeypatch.setattr(module, 'source_service', sources)
    monkeypatch.setattr(module, 'agent', AgentRuntime(UnavailableInference(), build_tool_registry(catalog, sources), sources=sources))
    monkeypatch.setattr(module.settings, 'chat_db_path', tmp_path / 'chat.db')
    async with module.app.router.lifespan_context(module.app):
        async with AsyncClient(transport=ASGITransport(app=module.app), base_url='http://test') as client:
            uploaded = await client.post('/sources/csv', files={'file': ('synthetic.csv',
                b'id;event_date;category;amount\n001;2024-01-01;A;1,5\n002;2024-02-03;B;2\n002;2024-02-03;B;2\n', 'text/csv')})
            assert uploaded.status_code == 200
            source_id = uploaded.json()['source_id']
            profile = await client.get(f'/sources/{source_id}/profile')
            assert profile.status_code == 200
            assert profile.json()['processed_rows'] == 3
            questions = [
                ('Что передо мной?', 'dataset_overview'),
                ('Что есть в этих данных?', 'dataset_overview'),
                ('Какие есть столбцы?', 'source_schema'),
                ('А какие значения встречаются чаще всего?', 'frequencies'),
                ('А теперь есть ли тут дубликаты?', 'duplicates'),
                ('А теперь покажи первые строки', 'preview'),
                ('Что ещё можешь скзаать про эти данные?', 'dataset_overview'),
            ]
            chat_id = None
            for question, intent in questions:
                path = '/agent/chat' + (f'?chat_id={chat_id}' if chat_id else '')
                response = await client.post(path, json={'question': question, 'source_ids': [source_id]})
                assert response.status_code == 200
                body = response.json()
                assert body['status'] == 'answered'
                assert body['analysis']['intent'] == intent
                assert body['timing']['calls'] == []
                assert chat_id is None or body['chat_id'] == chat_id
                chat_id = body['chat_id']
                if intent == 'dataset_overview':
                    assert '3 строки' in body['answer']
                    assert '01.01.2024' in body['answer'] and '03.02.2024' in body['answer']
                elif intent == 'frequencies':
                    assert any(result['rows'] == [[2, 'B'], [1, 'A']] for result in body['results'])
                elif intent == 'duplicates':
                    assert body['results'][0]['rows'] == [[1, 1]]
                elif intent == 'preview':
                    assert body['results'][0]['rows'][0][0] == '001'
            assert scans.call_count == 1
            history = (await client.get(f'/chats/{chat_id}')).json()
            assert history['source_id'] == source_id
            assert len(history['messages']) == 2 * len(questions)
            saved = [m['analysis_payload']['response'] for m in history['messages'] if m['role'] == 'assistant']
            assert [r['analysis']['intent'] for r in saved] == [intent for _, intent in questions]
            assert all(r['answer'] for r in saved)
            # A different source must not inherit this chat's data or cached facts.
            other = await client.post('/sources/csv', files={'file': ('other.csv', b'other_field\nZ\n', 'text/csv')})
            other_id = other.json()['source_id']
            conflict = await client.post(f'/agent/chat?chat_id={chat_id}', json={
                'question': 'Что передо мной?', 'source_ids': [other_id]})
            assert conflict.status_code == 409
            fresh = await client.post('/agent/chat', json={'question': 'Что передо мной?', 'source_ids': [other_id]})
            assert fresh.json()['chat_id'] != chat_id
            assert 'other_field' in fresh.json()['answer']
            assert 'event_date' not in fresh.json()['answer']
            assert scans.call_count == 2

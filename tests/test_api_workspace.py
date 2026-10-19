"""Contract exercised by the workspace, against the real FastAPI and CSV service."""

import importlib

from httpx import ASGITransport, AsyncClient
import pytest


@pytest.mark.asyncio
async def test_workspace_csv_to_agent_contract(tmp_path, monkeypatch):
    monkeypatch.setenv('LLM_PROVIDER', 'mock')
    monkeypatch.setenv('BI_DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.setenv('CATALOG_DB_PATH', str(tmp_path / 'catalog.sqlite3'))
    monkeypatch.setenv('CHAT_DB_PATH', str(tmp_path / 'chats.sqlite3'))
    module = importlib.import_module('app.main')
    async with module.app.router.lifespan_context(module.app), AsyncClient(transport=ASGITransport(app=module.app), base_url='http://test') as client:
        assert (await client.get('/health')).json()['llm_provider'] == 'mock'
        assert (await client.get('/sources')).json() == []
        assert (await client.get('/chats')).json() == []
        empty = await client.post('/sources/csv', files={'file': ('empty.csv', b'', 'text/csv')})
        assert empty.status_code == 400
        upload = await client.post('/sources/csv', files={'file': ('sales.csv', b'id,revenue\n001,10\n002,20\n', 'text/csv')})
        assert upload.status_code == 200
        source_id = upload.json()['source_id']
        assert (await client.get('/sources')).json()[0]['source_id'] == source_id
        schema = (await client.get(f'/sources/{source_id}/schema')).json()
        assert schema['objects'][0]['row_count'] == 2
        assert schema['objects'][0]['fields'][0]['inferred_type'] == 'string'
        preview = (await client.get(f'/sources/{source_id}/preview?limit=100')).json()
        assert preview == [{'id': '001', 'revenue': '10'}, {'id': '002', 'revenue': '20'}]
        profile = (await client.get(f'/sources/{source_id}/profile')).json()
        assert profile['sample_size'] == 2
        assert profile['columns']['id']['sample_null_count'] == 0
        result = await client.post('/agent/ask', json={'question': 'Что есть в данных?', 'source_ids': [source_id]})
        assert result.status_code == 200
        answer = result.json()
        assert answer['answer']
        assert answer['tool_results'][0]['tool_name'] == 'preview_data'
        assert answer['tool_results'][0]['ok']
        assert answer['tool_results'][0]['data'][0] == {'id': '001', 'revenue': '10'}
        assert (await client.get('/chats')).json() == [], 'Stateless UI questions must not create persistent chats'
        assert (await client.post('/agent/ask', json={'question': '', 'source_ids': [source_id]})).status_code == 422
        assert (await client.get('/sources/missing/schema')).status_code == 404
